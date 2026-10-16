import os
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"

SETTINGS_PATH = APP_DIR / "settings.yaml"
REPO_MODELS_DIR = APP_DIR / "models"

DATA_DIR = APP_DIR / "app_data"
ORIGINALS_DIR = DATA_DIR / "originals"
THUMBS_DIR = DATA_DIR / "thumbs"
WEIGHTS_DIR = DATA_DIR / "weights"
HISTORY_PATH = DATA_DIR / "history.json"
INSTANCE_PATH = DATA_DIR / "instance.json"
LOG_PATH = DATA_DIR / "app.log"

_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def ensure_dirs():
    for d in (DATA_DIR, ORIGINALS_DIR, THUMBS_DIR, WEIGHTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def safe_filename(name, fallback="image"):
    """Reduce an untrusted file name to a plain, Windows-safe base name."""
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = _BAD_CHARS.sub("_", name).strip(" .")
    if not name:
        name = fallback
    stem, ext = os.path.splitext(name)
    if stem.upper() in _RESERVED:
        stem = "_" + stem
    return stem[:120] + ext[:12]


def resolve_dir(value):
    """Resolve a user-supplied directory; relative paths are relative to the app folder."""
    p = Path(os.path.expandvars(os.path.expanduser(str(value or "output"))))
    if not p.is_absolute():
        p = APP_DIR / p
    return p.resolve()


def unique_path(directory, stem, ext, overwrite=False):
    candidate = directory / f"{stem}{ext}"
    if overwrite:
        return candidate
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({n}){ext}"
        n += 1
    return candidate
