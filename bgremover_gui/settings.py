import copy
import os
import re
import threading

import yaml

from .paths import SETTINGS_PATH

MODELS = ("u2net", "u2netp", "u2net_human_seg", "birefnet", "colorkey")

# section -> key -> (kind, default, *constraints)
SCHEMA = {
    "appearance": {
        "theme": ("choice", "system", ("system", "light", "dark")),
        "viewer_background": ("choice", "checker", ("checker", "light", "dark")),
        "thumbnail_size": ("choice", "medium", ("small", "medium", "large")),
        "thumbnail_fit": ("choice", "full", ("full", "crop")),
        "thumbnail_padding": ("int", 12, 0, 40),  # pixels of checkerboard around the image in Full view
        "queue_order": ("choice", "oldest", ("oldest", "newest")),
        "history_sort": ("choice", "newest", ("newest", "oldest", "name", "largest")),
        "last_view": ("choice", "workspace", ("workspace", "history", "settings")),
    },
    "processing": {
        "model": ("choice", "u2net", MODELS),
        "device": ("choice", "auto", ("auto", "gpu", "cpu")),
        "precision": ("choice", "half", ("half", "full")),
        "unload_after_minutes": ("int", 5, 0, 240),  # 0 keeps the model loaded until the app exits
        "auto_start": ("bool", True),
        "alpha_matting": ("bool", False),
        "alpha_matting_foreground_threshold": ("int", 240, 0, 255),
        "alpha_matting_background_threshold": ("int", 10, 0, 255),
        "alpha_matting_erode_size": ("int", 10, 0, 50),
        "alpha_matting_base_size": ("int", 1000, 200, 4000),
        "mask_threshold_enabled": ("bool", False),
        "mask_threshold": ("int", 128, 0, 255),
        # Color key (no AI): which colour to remove and how closely pixels must match it.
        "key_color_auto": ("bool", True),
        "key_color": ("color", "#ffffff"),
        "key_tolerance": ("int", 6, 0, 100),
        "key_softness": ("int", 8, 0, 100),
        "key_scope": ("choice", "everywhere", ("everywhere", "edges")),
    },
    "output": {
        "mode": ("choice", "transparent", ("transparent", "color", "mask")),
        "background_color": ("color", "#ffffff"),
        "format": ("choice", "png", ("png", "webp")),
        "auto_trim": ("bool", False),
        "directory": ("str", "output", 500),
        "suffix": ("str", "_nobg", 40),
        "keep_originals": ("bool", True),
        "overwrite_existing": ("bool", False),
        "confirm_x_delete": ("bool", False),  # ask before the X on a workspace thumbnail deletes the image
    },
    "watch": {
        "screenshots": ("bool", False),
        "downloads": ("bool", False),
    },
    "app": {
        "port": ("int", 8765, 1024, 65535),
        "shutdown_grace_seconds": ("int", 3, 2, 60),
    },
}

HEADER = (
    "# Background Remover GUI settings.\n"
    "# Written by the app whenever a setting changes; safe to edit while the app is closed.\n"
)

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SUFFIX_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _coerce(spec, value):
    kind, default = spec[0], spec[1]
    if kind == "choice":
        return value if value in spec[2] else default
    if kind == "bool":
        return value if isinstance(value, bool) else default
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return max(spec[2], min(spec[3], int(value)))
    if kind == "color":
        return value.lower() if isinstance(value, str) and _COLOR.match(value) else default
    if kind == "str":
        if not isinstance(value, str):
            return default
        return value.strip()[: spec[2]]
    return default


def sanitize(raw):
    """Return a complete, valid settings dict; unknown keys are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for section, keys in SCHEMA.items():
        src = raw.get(section) if isinstance(raw.get(section), dict) else {}
        out[section] = {k: _coerce(spec, src.get(k, spec[1])) for k, spec in keys.items()}
    out["output"]["suffix"] = _SUFFIX_BAD.sub("_", out["output"]["suffix"])
    if not out["output"]["directory"]:
        out["output"]["directory"] = SCHEMA["output"]["directory"][1]
    return out


class Settings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data = sanitize({})
        self.load()

    def load(self):
        raw = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except FileNotFoundError:
            pass
        except (OSError, yaml.YAMLError):
            # Keep the unreadable file for inspection instead of silently overwriting it.
            try:
                os.replace(self.path, str(self.path) + ".invalid")
            except OSError:
                pass
        with self._lock:
            self._data = sanitize(raw)
            self._save_locked()

    def get(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, patch):
        """Merge a partial {section: {key: value}} patch, validate and persist."""
        with self._lock:
            merged = copy.deepcopy(self._data)
            if isinstance(patch, dict):
                for section, values in patch.items():
                    if section in merged and isinstance(values, dict):
                        merged[section].update(values)
            self._data = sanitize(merged)
            self._save_locked()
            return copy.deepcopy(self._data)

    def _save_locked(self):
        tmp = str(self.path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(HEADER)
            yaml.safe_dump(self._data, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, self.path)
