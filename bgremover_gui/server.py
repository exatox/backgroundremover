"""
Local HTTP server for the GUI (standard library only).

Bound to 127.0.0.1. Every /api call needs the per-launch token that is embedded
in the served page, and Host/Origin are checked, so other websites open in the
browser cannot drive the app. The process exits once the last tab is closed.
"""

import hmac
import io
import json
import logging
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from PIL import Image, ImageOps

from .paths import INSTANCE_PATH, WEB_DIR, resolve_dir

log = logging.getLogger("bgremover")

APP_ID = "bgremover-gui"
STARTUP_TIMEOUT = 120  # seconds to wait for the first tab before giving up

STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
}
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
}
CSP = "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"

PICK_FOLDER_SCRIPT = """
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = filedialog.askdirectory(initialdir=sys.argv[1], title="Choose output folder", parent=root)
sys.stdout.buffer.write((path or "").encode("utf-8"))
"""


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, app):
        super().__init__(address, Handler)
        self.app = app
        self.token = secrets.token_urlsafe(32)
        self.port = self.server_address[1]
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.picker_lock = threading.Lock()

    def handle_error(self, request, client_address):
        # A tab closing mid-request is normal; keep it out of the log.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        log.exception("Request from %s failed", client_address)

    def watch_tabs(self):
        """Exit when no tab has been connected for the configured grace period."""
        started = time.monotonic()
        seen, empty_since = False, None
        while True:
            time.sleep(0.25)
            now = time.monotonic()
            if self.app.events.count():
                seen, empty_since = True, None
            elif not seen:
                if now - started > STARTUP_TIMEOUT:
                    self.quit("no tab connected")
            elif empty_since is None:
                empty_since = now
            elif now - empty_since >= self.app.settings.get()["app"]["shutdown_grace_seconds"]:
                self.quit("last tab closed")

    def quit(self, reason):
        log.info("Shutting down: %s", reason)
        try:
            os.remove(INSTANCE_PATH)
        except OSError:
            pass
        logging.shutdown()
        os._exit(0)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BackgroundRemoverGUI"
    sys_version = ""
    timeout = 120

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    # -- plumbing -------------------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def _dispatch(self, method):
        try:
            url = urlsplit(self.path)
            self.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            path = url.path
            if self.headers.get("Host") not in self.server.hosts:
                raise HttpError(403, "Forbidden host")
            origin = self.headers.get("Origin")
            if origin and origin not in self.server.origins:
                raise HttpError(403, "Forbidden origin")

            if path.startswith("/api/"):
                if path == "/api/ping":
                    return self._json({"app": APP_ID})
                token = self.headers.get("X-BGR-Token") or self.query.get("t", "")
                if not hmac.compare_digest(token.encode(), self.server.token.encode()):
                    raise HttpError(403, "Invalid session token. Reload the page.")
                return self._api(method, path[5:])
            if method != "GET":
                raise HttpError(405, "Method not allowed")
            if path == "/":
                return self._index()
            if path == "/favicon.ico":
                return self._static("icon.ico")
            if path.startswith("/static/"):
                return self._static(path[8:])
            raise HttpError(404, "Not found")
        except HttpError as e:
            self._discard_body()
            self._json({"error": e.message}, e.status)
        except (ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception as e:
            log.exception("Unhandled error for %s %s", method, self.path)
            try:
                self._json({"error": str(e) or type(e).__name__}, 500)
            except OSError:
                pass
            self.close_connection = True

    def _discard_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if 0 < length <= 1 << 20:
            self.rfile.read(length)
        elif length:
            self.close_connection = True

    def _send(self, body, content_type, status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {"Cache-Control": "no-store"}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj).encode("utf-8"), "application/json", status)

    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1 << 20:
            raise HttpError(413, "Request too large")
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            raise HttpError(400, "Invalid JSON")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _ids(value):
        if not isinstance(value, list):
            return None
        return [v for v in value if isinstance(v, str)]

    # -- pages ----------------------------------------------------------------
    def _index(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        theme = self.server.app.settings.get()["appearance"]["theme"]
        html = html.replace("__TOKEN__", self.server.token).replace("__THEME__", theme)
        self._send(
            html.encode("utf-8"),
            "text/html; charset=utf-8",
            headers={"Cache-Control": "no-store", "Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer"},
        )

    def _static(self, name):
        ext = os.path.splitext(name)[1]
        target = WEB_DIR / name
        if "/" in name or "\\" in name or ext not in STATIC_TYPES or not target.is_file():
            raise HttpError(404, "Not found")
        self._send(target.read_bytes(), STATIC_TYPES[ext], headers={"Cache-Control": "no-cache"})

    # -- api ------------------------------------------------------------------
    def _api(self, method, route):
        app = self.server.app
        if method == "GET":
            if route == "state":
                return self._json(app.state())
            if route == "history":
                return self._json({"history": app.refresh_history()})
            if route == "events":
                return self._events()
            if route == "zip":
                return self._zip()
            if route.startswith("file/"):
                return self._file(route[5:])
            raise HttpError(404, "Not found")

        if method == "PUT" and route == "settings":
            return self._json({"settings": app.update_settings(self._body_json())})

        if method == "POST":
            if route == "upload":
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    job = app.add_upload(self.query.get("name", ""), self.rfile, length)
                    if self.query.get("start"):
                        app.start([job["id"]])
                    return self._json({"job": job})
                except ValueError as e:
                    raise HttpError(400, str(e))
            body = self._body_json()
            if route == "start":
                app.start(self._ids(body.get("ids")))
                return self._json({"ok": True})
            if route == "jobs/remove":
                scope = body.get("scope")
                statuses = {"finished": ("done", "error"), "waiting": ("pending", "queued")}.get(
                    scope, ("pending", "queued", "done", "error")
                )
                app.remove_jobs(self._ids(body.get("ids")), statuses)
                return self._json({"ok": True})
            if route == "reprocess":
                try:
                    return self._json({"job": app.reprocess(str(body.get("id", "")))})
                except ValueError as e:
                    raise HttpError(400, str(e))
            if route == "trim":
                try:
                    return self._json({"entry": app.trim(str(body.get("id", "")))})
                except ValueError as e:
                    raise HttpError(400, str(e))
            if route == "history/delete":
                removed, errors = app.delete_history(self._ids(body.get("ids")) or [])
                return self._json({"removed": removed, "errors": errors})
            if route == "reveal":
                entry = app.history.get(str(body.get("id", "")))
                if not entry or not os.path.exists(entry["output_path"]):
                    raise HttpError(404, "File no longer exists")
                subprocess.Popen(f'explorer /select,"{os.path.normpath(entry["output_path"])}"')
                return self._json({"ok": True})
            if route == "open-output":
                folder = resolve_dir(app.settings.get()["output"]["directory"])
                folder.mkdir(parents=True, exist_ok=True)
                os.startfile(folder)
                return self._json({"ok": True})
            if route == "pick-folder":
                return self._json({"path": self._pick_folder()})
            if route == "bye":
                app.events.close(self.query.get("cid", ""))
                return self._json({"ok": True})
            if route == "quit":
                self._json({"ok": True})
                self.wfile.flush()
                threading.Timer(0.2, self.server.quit, args=("quit requested",)).start()
                return
        raise HttpError(404, "Not found")

    def _events(self):
        app = self.server.app
        client_id = self.query.get("cid") or secrets.token_hex(8)
        q = app.events.subscribe(client_id)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while True:
                try:
                    item = q.get(timeout=2)
                except queue.Empty:
                    payload = b": keep-alive\n\n"
                else:
                    if item is None:
                        break
                    payload = f"event: {item[0]}\ndata: {json.dumps(item[1])}\n\n".encode("utf-8")
                self.wfile.write(payload)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            app.events.unsubscribe(client_id, q)

    def _file(self, spec):
        entry_id, _, kind = spec.partition("/")
        entry = self.server.app.history.get(entry_id)
        if not entry:
            raise HttpError(404, "Not found")
        path = {
            "output": entry["output_path"],
            "png": entry["output_path"],
            "thumb": entry.get("thumb_path"),
            "original": entry.get("original_path"),
        }.get(kind)
        if not path or not os.path.isfile(path):
            raise HttpError(404, "File no longer exists")

        ext = os.path.splitext(path)[1].lower()
        name = os.path.basename(entry["output_path"]) if kind != "original" else entry["name"]
        convert = (kind == "png" and ext != ".png") or (kind == "original" and ext not in IMAGE_TYPES)
        if convert:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                if im.mode not in ("RGB", "RGBA", "L", "LA"):
                    im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
                buf = io.BytesIO()
                im.save(buf, "PNG", compress_level=3)
            body, content_type = buf.getvalue(), "image/png"
            name = os.path.splitext(name)[0] + ".png"
        else:
            with open(path, "rb") as f:
                body = f.read()
            content_type = IMAGE_TYPES.get(ext, "application/octet-stream")

        headers = {"Cache-Control": "private, max-age=86400"}
        if self.query.get("dl"):
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
        self._send(body, content_type, headers=headers)

    def _zip(self):
        app = self.server.app
        ids = [i for i in self.query.get("ids", "").split(",") if i]
        with tempfile.TemporaryFile() as tmp:
            used = set()
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
                for entry_id in ids:
                    entry = app.history.get(entry_id)
                    if not entry or not os.path.isfile(entry["output_path"]):
                        continue
                    stem, ext = os.path.splitext(os.path.basename(entry["output_path"]))
                    name, n = stem + ext, 2
                    while name.lower() in used:
                        name, n = f"{stem} ({n}){ext}", n + 1
                    used.add(name.lower())
                    z.write(entry["output_path"], name)
            if not used:
                raise HttpError(404, "None of the selected files exist any more")
            size = tmp.tell()
            tmp.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", 'attachment; filename="background-removed.zip"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                chunk = tmp.read(1 << 20)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _pick_folder(self):
        """Native folder dialog, run in a child process so Tk never touches server threads."""
        if not self.server.picker_lock.acquire(blocking=False):
            raise HttpError(409, "A folder dialog is already open")
        try:
            current = resolve_dir(self.server.app.settings.get()["output"]["directory"])
            start = current if current.is_dir() else current.parent
            result = subprocess.run(
                [sys.executable, "-I", "-c", PICK_FOLDER_SCRIPT, str(start)],
                capture_output=True,
                timeout=900,
            )
            return os.path.normpath(result.stdout.decode("utf-8")) if result.stdout else ""
        except subprocess.TimeoutExpired:
            return ""
        finally:
            self.server.picker_lock.release()
