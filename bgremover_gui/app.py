import filecmp
import logging
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from . import __version__
from .engine import Engine, content_box, matting_available, weights_present
from .history import History
from .paths import HISTORY_PATH, ORIGINALS_DIR, SETTINGS_PATH, THUMBS_DIR, resolve_dir, safe_filename, unique_path
from .settings import MODELS, Settings
from .watcher import FolderWatcher

log = logging.getLogger("bgremover")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif")
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
THUMB_SIZE = 560


def save_image(img, path):
    """Write atomically, picking the format from the file extension."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if path.suffix.lower() == ".webp":
        img.save(tmp, "WEBP", quality=95, method=4)
    else:
        img.save(tmp, "PNG")
    os.replace(tmp, path)


def save_thumbnail(img, path):
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
    thumb.save(path, "WEBP", quality=88)


class Events:
    """Fan-out of server-sent events to every connected browser tab."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {}

    def subscribe(self, client_id):
        q = queue.Queue()
        with self._lock:
            self._clients[client_id] = q
        return q

    def unsubscribe(self, client_id, q):
        with self._lock:
            if self._clients.get(client_id) is q:
                del self._clients[client_id]

    def close(self, client_id):
        with self._lock:
            q = self._clients.get(client_id)
        if q:
            q.put(None)

    def count(self):
        with self._lock:
            return len(self._clients)

    def publish(self, event, data):
        with self._lock:
            clients = list(self._clients.values())
        for q in clients:
            q.put((event, data))


class Job:
    def __init__(self, name, src):
        self.id = src.stem
        self.name = name
        self.src = src
        self.status = "pending"  # pending | queued | processing | done | error
        self.stage = ""
        self.error = ""
        self.history_id = None
        self.created = time.time()

    def public(self):
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "stage": self.stage,
            "error": self.error,
            "history_id": self.history_id,
            "created": self.created,
        }


class App:
    def __init__(self):
        self.settings = Settings()
        self.history = History(HISTORY_PATH)
        self.engine = Engine()
        self.events = Events()
        self.engine.on_change = lambda: self.events.publish("info", self.info())
        self.jobs = {}
        self._cv = threading.Condition()
        self._info = {"ready": False}
        self._own_outputs = set()
        try:
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except Exception:
            pass
        self._sweep_orphans()
        self.watcher = FolderWatcher(self, IMAGE_EXTENSIONS)
        threading.Thread(target=self._worker, name="worker", daemon=True).start()
        self.watcher.start()

    # -- state ----------------------------------------------------------------
    def info(self):
        s = self.settings.get()
        return dict(
            self._info,
            version=__version__,
            models=list(MODELS),
            settings_path=str(SETTINGS_PATH),
            output_dir=str(resolve_dir(s["output"]["directory"])),
            extensions=list(IMAGE_EXTENSIONS),
            watch_folders={key: str(folder) for key, folder in self.watcher.folders.items()},
            loaded_model=self.engine.loaded(),
            birefnet_downloaded=weights_present("birefnet"),
        )

    def state(self):
        entries, _ = self.history.list()
        with self._cv:
            jobs = [j.public() for j in self.jobs.values()]
        return {"settings": self.settings.get(), "jobs": jobs, "history": entries, "info": self.info()}

    def update_settings(self, patch):
        settings = self.settings.update(patch)
        self.events.publish("settings", settings)
        self.events.publish("info", self.info())
        return settings

    def refresh_history(self):
        entries, pruned = self.history.list()
        if pruned:
            self.events.publish("history_remove", pruned)
        return entries

    # -- queue ----------------------------------------------------------------
    def add_upload(self, name, stream, length):
        name = safe_filename(name)
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {ext or 'unknown'}")
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            raise ValueError("File is empty or too large.")
        src = ORIGINALS_DIR / f"{uuid.uuid4().hex}{ext}"
        remaining = length
        with open(src, "wb") as f:
            while remaining:
                chunk = stream.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if remaining:
            src.unlink(missing_ok=True)
            raise ValueError("Upload was interrupted.")
        return self._add_job(Job(name, src))

    def add_watched(self, path):
        """Queue an image that appeared in a watched folder.

        Returns False when the file cannot be read yet (still locked by the app
        writing it), so the watcher tries again on its next pass.
        """
        if self._is_own_output(path):
            return True
        name = safe_filename(os.path.basename(path))
        src = ORIGINALS_DIR / f"{uuid.uuid4().hex}{os.path.splitext(name)[1].lower()}"
        try:
            shutil.copyfile(path, src)
        except OSError:
            src.unlink(missing_ok=True)
            return False
        job = self._add_job(Job(name, src))
        if self.settings.get()["processing"]["auto_start"]:
            self.start([job["id"]])
        return True

    def _is_own_output(self, path):
        """True for files this app wrote, including copies of results downloaded from the page."""
        if os.path.normcase(os.path.abspath(path)) in self._own_outputs:
            return True
        try:
            size = os.path.getsize(path)
            for output, known_size in self.history.outputs():
                if known_size == size and os.path.exists(output) and filecmp.cmp(path, output, shallow=False):
                    return True
        except OSError:
            pass
        return False

    def trim(self, entry_id):
        """Crop a finished result in place to the bounding box of its visible pixels."""
        entry = self.history.get(entry_id)
        if not entry or not os.path.exists(entry["output_path"]):
            raise ValueError("The file no longer exists.")
        with Image.open(entry["output_path"]) as im:
            im.load()
        if "A" in im.getbands():
            channel = im.getchannel("A")
        elif entry.get("mode") == "mask":
            channel = im.convert("L")
        else:
            raise ValueError("This image has no transparent area to trim.")
        if not channel.getbbox():
            raise ValueError("This image is completely empty.")
        box = content_box(channel)
        if box is None:
            raise ValueError("Already trimmed: there is no empty margin left.")

        trimmed = im.crop(box)
        save_image(trimmed, entry["output_path"])
        save_thumbnail(trimmed, entry["thumb_path"])
        source_size = entry.get("source_size") or [im.width, im.height]
        left, top = (entry.get("crop") or [0, 0])[:2]
        updated = self.history.update(
            entry_id,
            {
                "width": trimmed.width,
                "height": trimmed.height,
                "bytes": os.path.getsize(entry["output_path"]),
                "source_size": source_size,
                "crop": [left + box[0], top + box[1], left + box[2], top + box[3]],
            },
        )
        self.events.publish("history_update", updated)
        return updated

    def reprocess(self, entry_id):
        entry = self.history.get(entry_id)
        original = entry and entry.get("original_path")
        if not original or not os.path.exists(original):
            raise ValueError("The original image is no longer available.")
        src = ORIGINALS_DIR / f"{uuid.uuid4().hex}{os.path.splitext(original)[1]}"
        shutil.copyfile(original, src)
        job = self._add_job(Job(entry["name"], src))
        self.start([job["id"]])
        return job

    def _add_job(self, job):
        with self._cv:
            self.jobs[job.id] = job
        self.events.publish("job", job.public())
        return job.public()

    def start(self, ids=None):
        with self._cv:
            for job in self.jobs.values():
                if job.status == "pending" and (ids is None or job.id in ids):
                    job.status = "queued"
                    self.events.publish("job", job.public())
            self._cv.notify_all()

    def remove_jobs(self, ids=None, statuses=("pending", "queued", "done", "error")):
        """Drop jobs from the queue view. Results already written stay in the history."""
        with self._cv:
            doomed = [j for j in self.jobs.values() if j.status in statuses and (ids is None or j.id in ids)]
            for job in doomed:
                del self.jobs[job.id]
                if job.status in ("pending", "queued"):
                    job.src.unlink(missing_ok=True)
            remaining = [j.public() for j in self.jobs.values()]
        self.events.publish("jobs", remaining)

    def delete_history(self, ids):
        removed, errors = self.history.remove(ids)
        if removed:
            with self._cv:
                for job in [j for j in self.jobs.values() if j.history_id in removed]:
                    del self.jobs[job.id]
                remaining = [j.public() for j in self.jobs.values()]
            self.events.publish("jobs", remaining)
            self.events.publish("history_remove", removed)
        return removed, errors

    # -- worker ---------------------------------------------------------------
    def _worker(self):
        self._warmup()
        while True:
            with self._cv:
                job = next((j for j in self.jobs.values() if j.status == "queued"), None)
                if job is None:
                    self._cv.wait(timeout=10)
                    self._unload_if_idle()
                    continue
                job.status = "processing"
                job.stage = "Starting…"
            self.events.publish("job", job.public())
            try:
                job.history_id = self._process(job)
                job.status = "done"
            except Exception as e:
                log.exception("Processing failed for %s", job.name)
                job.status = "error"
                job.error = str(e).strip() or type(e).__name__
                job.src.unlink(missing_ok=True)
            job.stage = ""
            self.events.publish("job", job.public())

    def _warmup(self):
        try:
            self._info = dict(self.engine.info(), ready=True, matting=matting_available())
        except Exception as e:
            log.exception("PyTorch failed to initialise")
            self._info = {"ready": True, "cuda": False, "error": str(e)}
        self.events.publish("info", self.info())
        try:
            s = self.settings.get()["processing"]
            # A model that still has to be downloaded is fetched with the first image instead,
            # where the download progress can be shown.
            if weights_present(s["model"]):
                self.engine.load(s["model"], s["device"], s["precision"])
        except Exception:
            log.exception("Model preload failed")

    def _unload_if_idle(self):
        minutes = self.settings.get()["processing"]["unload_after_minutes"]
        if minutes and self.engine.idle_seconds() >= minutes * 60:
            if self.engine.unload():
                log.info("Released the model after %s idle minute(s)", minutes)

    def _process(self, job):
        started = time.time()
        s = self.settings.get()
        proc, out = s["processing"], s["output"]

        def stage(text):
            job.stage = text
            self.events.publish("job", job.public())

        with Image.open(job.src) as im:
            img = ImageOps.exif_transpose(im).convert("RGB")
        result, crop = self.engine.process(img, proc, out, on_stage=stage)
        stage("Saving…")

        out_dir = resolve_dir(out["directory"])
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = "." + out["format"]
        stem = os.path.splitext(job.name)[0] + out["suffix"]
        out_path = unique_path(out_dir, stem, ext, overwrite=out["overwrite_existing"])
        self._own_outputs.add(os.path.normcase(str(out_path)))  # keeps the folder watcher from re-queuing it
        save_image(result, out_path)

        thumb_path = THUMBS_DIR / f"{job.id}.webp"
        save_thumbnail(result, thumb_path)

        original_path = str(job.src)
        if not out["keep_originals"]:
            job.src.unlink(missing_ok=True)
            original_path = None

        self.events.publish(
            "history_add",
            self.history.add(
                {
                    "id": job.id,
                    "name": job.name,
                    "output_path": str(out_path),
                    "original_path": original_path,
                    "thumb_path": str(thumb_path),
                    "created": time.time(),
                    "model": proc["model"],
                    "mode": out["mode"],
                    "alpha_matting": bool(proc["alpha_matting"] and out["mode"] != "mask"),
                    "format": out["format"],
                    "width": result.width,
                    "height": result.height,
                    "source_size": [img.width, img.height],
                    "crop": list(crop) if crop else None,
                    "rev": 0,
                    "bytes": out_path.stat().st_size,
                    "seconds": round(time.time() - started, 2),
                    "device": self.engine.pick_device(proc["device"]),
                    "precision": self.engine.effective_precision(proc["model"], proc["device"], proc["precision"]),
                }
            ),
        )
        return job.id

    def _sweep_orphans(self):
        """Remove staged uploads and thumbnails left behind by a previous session."""
        self.history.list()
        keep = self.history.referenced_files()
        for folder in (ORIGINALS_DIR, THUMBS_DIR):
            for f in Path(folder).iterdir():
                if f.is_file() and os.path.normcase(str(f)) not in keep:
                    try:
                        f.unlink()
                    except OSError:
                        pass
