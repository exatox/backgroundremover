"""Watches the Screenshots / Downloads folders and queues images that appear in them."""

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("bgremover")

KNOWN_FOLDERS = {
    "screenshots": ("{B7BEDE81-DF94-4682-A7D8-57A52620B86F}", Path.home() / "Pictures" / "Screenshots"),
    "downloads": ("{374DE290-123F-4565-9164-39C4925E467B}", Path.home() / "Downloads"),
}


class _GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


def known_folder(key):
    """Resolve a Windows known folder (follows OneDrive redirection); falls back to the usual location."""
    guid_text, fallback = KNOWN_FOLDERS[key]
    try:
        guid = _GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid_text), ctypes.byref(guid))
        pointer = ctypes.c_void_p()
        ctypes.oledll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer))
        try:
            return Path(ctypes.wstring_at(pointer.value))
        finally:
            ctypes.windll.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ctypes.windll.ole32.CoTaskMemFree(pointer)
    except Exception:
        return fallback


class FolderWatcher(threading.Thread):
    """Polls the enabled folders once a second. Only files that appear after a folder
    is switched on are queued, and only once their size has stopped changing."""

    def __init__(self, app, extensions, interval=1.0):
        super().__init__(name="folder-watcher", daemon=True)
        self.app = app
        self.extensions = extensions
        self.interval = interval
        self.folders = {key: known_folder(key) for key in KNOWN_FOLDERS}
        self._seen = {}
        self._pending = {}

    def run(self):
        while True:
            time.sleep(self.interval)
            try:
                self.tick()
            except Exception:
                log.exception("Folder watcher error")

    def tick(self):
        enabled = self.app.settings.get()["watch"]
        for key, folder in self.folders.items():
            if not enabled.get(key):
                self._seen.pop(key, None)
                continue
            try:
                with os.scandir(folder) as it:
                    current = {e.name: e for e in it if e.name.lower().endswith(self.extensions) and e.is_file()}
            except OSError:
                continue
            if key not in self._seen:
                self._seen[key] = set(current)  # baseline: ignore what is already there
                continue
            seen = self._seen[key]
            seen &= set(current)  # forget deleted files so a reused name is picked up again
            for name, entry in current.items():
                if name in seen:
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                signature = (stat.st_size, stat.st_mtime_ns)
                if stat.st_size == 0 or self._pending.get(entry.path) != signature:
                    self._pending[entry.path] = signature  # still being written; look again next tick
                    continue
                if self.app.add_watched(entry.path):
                    seen.add(name)
                    self._pending.pop(entry.path, None)
