import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path


def trash(path):
    """Send a file to the Recycle Bin (plain delete where that is unavailable)."""
    path = str(path)
    if not os.path.exists(path):
        return
    if os.name == "nt":
        try:

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", ctypes.c_void_p),
                    ("pTo", ctypes.c_void_p),
                    ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_void_p),
                ]

            # pFrom is a double-null-terminated list of paths.
            source = ctypes.create_unicode_buffer(path + "\0")
            op = SHFILEOPSTRUCTW()
            op.wFunc = 3  # FO_DELETE
            op.pFrom = ctypes.cast(source, ctypes.c_void_p)
            op.fFlags = 0x0040 | 0x0010 | 0x0400 | 0x0004  # ALLOWUNDO | NOCONFIRMATION | NOERRORUI | SILENT
            if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not os.path.exists(path):
                return
        except Exception:
            pass
    os.remove(path)


def _unlink(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


class History:
    """Index of processed images. Entries whose output file is gone are dropped on listing."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._items = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for entry in json.load(f):
                    if isinstance(entry, dict) and "id" in entry and "output_path" in entry:
                        self._items[entry["id"]] = entry
        except (OSError, ValueError):
            pass

    def _save(self):
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(self._items.values()), f, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def public(entry):
        out = {k: v for k, v in entry.items() if k not in ("original_path", "thumb_path")}
        out["output_name"] = os.path.basename(entry["output_path"])
        out["has_original"] = bool(entry.get("original_path")) and os.path.exists(entry["original_path"])
        return out

    def add(self, entry):
        with self._lock:
            self._items[entry["id"]] = entry
            self._save()
        return self.public(entry)

    def get(self, entry_id):
        with self._lock:
            return self._items.get(entry_id)

    def update(self, entry_id, fields):
        """Merge fields into an entry and bump its revision (used to refresh cached images)."""
        with self._lock:
            entry = self._items[entry_id]
            entry.update(fields)
            entry["rev"] = entry.get("rev", 0) + 1
            self._save()
            return self.public(entry)

    def outputs(self):
        with self._lock:
            return [(e["output_path"], e.get("bytes")) for e in self._items.values()]

    def list(self):
        """Newest first. Also prunes entries whose output no longer exists; returns (entries, pruned ids)."""
        with self._lock:
            gone = [e for e in self._items.values() if not os.path.exists(e["output_path"])]
            for entry in gone:
                _unlink(entry.get("original_path"))
                _unlink(entry.get("thumb_path"))
                del self._items[entry["id"]]
            if gone:
                self._save()
            entries = sorted(self._items.values(), key=lambda e: e.get("created", 0), reverse=True)
            return [self.public(e) for e in entries], [e["id"] for e in gone]

    def remove(self, ids):
        """Delete outputs (to the Recycle Bin) along with their kept originals and thumbnails."""
        removed, errors = [], []
        with self._lock:
            for entry_id in ids:
                entry = self._items.get(entry_id)
                if not entry:
                    continue
                try:
                    trash(entry["output_path"])
                except OSError as e:
                    errors.append(f"{os.path.basename(entry['output_path'])}: {e.strerror or e}")
                    continue
                _unlink(entry.get("original_path"))
                _unlink(entry.get("thumb_path"))
                del self._items[entry_id]
                removed.append(entry_id)
            if removed:
                self._save()
        return removed, errors

    def referenced_files(self):
        with self._lock:
            files = set()
            for e in self._items.values():
                files.update(os.path.normcase(p) for p in (e.get("original_path"), e.get("thumb_path")) if p)
            return files
