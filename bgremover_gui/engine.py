"""
Inference engine for the GUI.

Uses the U^2-Net definitions from the backgroundremover package (plus the
BiRefNet port in birefnet.py), but keeps the loaded network on the device
between images (bg.remove() reloads the weights from disk on every call) and
avoids importing the video stack. One model is resident at a time, and it is
released after the configured idle time.
"""

import gc
import hashlib
import os
import threading
import time
import urllib.request

import numpy as np
from PIL import Image

from .paths import REPO_MODELS_DIR, WEIGHTS_DIR

UPSTREAM_RAW = "https://github.com/nadermx/backgroundremover/raw/main/models/"
BIREFNET_URL = (
    "https://huggingface.co/ZhengPeng7/BiRefNet/resolve/"
    "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4/model.safetensors"
)

MODEL_NAMES = {
    "u2net": "General (u2net)",
    "u2net_human_seg": "People (u2net_human_seg)",
    "u2netp": "Lightweight (u2netp)",
    "birefnet": "High detail (BiRefNet)",
    "colorkey": "Color key",
}
AI_MODELS = ("u2net", "u2net_human_seg", "u2netp", "birefnet")

# Pixels at or below this alpha (about 8% opacity) count as empty when trimming, so the
# faint haze a mask can leave far from the subject does not hold the crop open.
TRIM_ALPHA = 20

# Weights ship in the repository's models/ folder (the two large ones split into parts).
WEIGHTS = {
    "u2net": {
        "parts": ("u2aa", "u2ab", "u2ac", "u2ad"),
        "sha256": "10025a17f49cd3208afc342b589890e402ee63123d6f2d289a4a0903695cce58",
    },
    "u2net_human_seg": {
        "parts": ("u2haa", "u2hab", "u2hac", "u2had"),
        "sha256": "13f0396e3f6fbc1d7ab55a8558640bef306a59b9110a5c595eb949ff69cf2414",
    },
    "u2netp": {
        "parts": ("u2netp.pth",),
        "sha256": "e7567cde013fb64813973ce6e1ecc25a80c05c3ca7adbc5a54f3c3d90991b854",
    },
    # Downloaded once from Hugging Face, pinned to a specific commit.
    "birefnet": {
        "url": BIREFNET_URL,
        "file": "birefnet.safetensors",
        "size": 444473596,
        "sha256": "9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154",
    },
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def weights_present(model_name):
    spec = WEIGHTS[model_name]
    return (WEIGHTS_DIR / spec.get("file", f"{model_name}.pth")).exists() or "url" not in spec


def ensure_weights(model_name, on_progress=None):
    """Return a checksum-verified weights file, assembling or downloading it if needed."""
    spec = WEIGHTS[model_name]
    target = WEIGHTS_DIR / spec.get("file", f"{model_name}.pth")
    if target.exists() and _sha256(target) == spec["sha256"]:
        return target

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    if "url" in spec:
        _download(spec["url"], tmp, spec["size"], on_progress)
        if _sha256(tmp) != spec["sha256"]:
            os.remove(tmp)
            raise RuntimeError(f"The downloaded '{model_name}' weights failed checksum verification.")
        os.replace(tmp, target)
        return target
    local = all((REPO_MODELS_DIR / p).exists() for p in spec["parts"])
    with open(tmp, "wb") as out:
        for part in spec["parts"]:
            if local:
                with open(REPO_MODELS_DIR / part, "rb") as src:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        out.write(chunk)
            else:
                with urllib.request.urlopen(UPSTREAM_RAW + part, timeout=120) as resp:
                    for chunk in iter(lambda: resp.read(1 << 20), b""):
                        out.write(chunk)
    if _sha256(tmp) != spec["sha256"]:
        os.remove(tmp)
        raise RuntimeError(f"Model weights for '{model_name}' failed checksum verification.")
    os.replace(tmp, target)
    return target


def _download(url, dest, expected_size, on_progress):
    report = on_progress or (lambda _fraction: None)
    done = 0
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as out:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            out.write(chunk)
            done += len(chunk)
            report(min(1.0, done / expected_size))


class Engine:
    def __init__(self):
        self._lock = threading.RLock()
        self._nets = {}  # (model, device, precision) -> network; at most one entry
        self._torch = None
        self._cuda_broken = False
        self.last_used = time.monotonic()
        self.on_change = lambda: None  # called when a model is loaded or released

    # -- device ---------------------------------------------------------------
    def torch(self):
        if self._torch is None:
            import torch

            self._torch = torch
        return self._torch

    def cuda_available(self):
        if self._cuda_broken:
            return False
        try:
            return bool(self.torch().cuda.is_available())
        except Exception:
            return False

    def pick_device(self, preference):
        if preference != "cpu" and self.cuda_available():
            return "cuda"
        return "cpu"

    def info(self):
        torch = self.torch()
        info = {"torch": torch.__version__, "cuda": self.cuda_available(), "gpu_name": None, "gpu_memory_mb": None}
        if info["cuda"]:
            try:
                info["gpu_name"] = torch.cuda.get_device_name(0)
                info["gpu_memory_mb"] = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
            except Exception:
                pass
        return info

    # -- model ----------------------------------------------------------------
    def _key(self, model_name, preference, precision):
        device = self.pick_device(preference)
        # Half precision is only used on the GPU, and only for BiRefNet: U^2-Net's masks
        # break down in float16, and its weights are small enough that it saves little.
        return model_name, device, precision if device == "cuda" and model_name == "birefnet" else "full"

    def effective_precision(self, model_name, preference, precision):
        return self._key(model_name, preference, precision)[2]

    def is_loaded(self, model_name, preference, precision="full"):
        return self._key(model_name, preference, precision) in self._nets

    def loaded(self):
        """Human-readable description of the resident model, or None."""
        for model_name, device, precision in list(self._nets):
            return f"{MODEL_NAMES.get(model_name, model_name)}, {precision} precision, {'GPU' if device == 'cuda' else 'CPU'}"
        return None

    def load(self, model_name, preference="auto", precision="full", on_progress=None):
        key = self._key(model_name, preference, precision)
        _, device, precision = key
        with self._lock:
            if key not in self._nets:
                self.unload()  # keep a single model resident so VRAM use stays bounded
                torch = self.torch()
                path = ensure_weights(model_name, on_progress)
                if model_name == "birefnet":
                    from . import birefnet

                    net = birefnet.build(path)
                else:
                    from backgroundremover.u2net import u2net

                    net = u2net.U2NETP(3, 1) if model_name == "u2netp" else u2net.U2NET(3, 1)
                    net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
                dtype = torch.float16 if precision == "half" else torch.float32
                net = net.to(device, dtype=dtype).eval()
                # One dummy pass at the working size, so GPU kernel setup happens here
                # (in the background at launch) rather than on the first real image.
                size = 1024 if model_name == "birefnet" else 320
                with torch.inference_mode():
                    net(torch.zeros(1, 3, size, size, device=device, dtype=dtype))
                self._nets[key] = net
                self.last_used = time.monotonic()
                self.on_change()
            return self._nets[key], device

    def unload(self):
        """Release the resident model and hand its GPU memory back to the driver."""
        with self._lock:
            if not self._nets:
                return False
            self._nets.clear()
            gc.collect()
            if self._torch is not None and self.cuda_available():
                self._torch.cuda.empty_cache()
        self.on_change()
        return True

    def idle_seconds(self):
        return time.monotonic() - self.last_used if self._nets else 0.0

    def predict_mask(self, img, model_name, preference="auto", precision="full"):
        """Return the saliency mask (mode L, same size as img) for an RGB PIL image."""
        with self._lock:
            try:
                return self._predict(img, model_name, preference, precision)
            except RuntimeError:
                if self.pick_device(preference) != "cuda":
                    raise
                # GPU failed (unsupported card, out of memory...): fall back to CPU for this session.
                self._cuda_broken = True
                self.unload()
                return self._predict(img, model_name, "cpu", "full")
            finally:
                self.last_used = time.monotonic()

    def _predict(self, img, model_name, preference, precision):
        torch = self.torch()
        F = torch.nn.functional
        net, device = self.load(model_name, preference, precision)
        dtype = next(net.parameters()).dtype
        mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
        with torch.inference_mode():
            x = torch.from_numpy(np.array(img)).to(device).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            if model_name == "birefnet":
                x = F.interpolate(x, size=(1024, 1024), mode="bilinear", antialias=True)
                pred = net(((x - mean) / std).to(dtype))[:, 0].float().sigmoid()
            else:
                x = F.interpolate(x, size=(320, 320), mode="bilinear", antialias=True)
                x = x / x.max().clamp_min(1e-8)
                pred = net(((x - mean) / std).to(dtype))[0][:, 0].float()
                lo, hi = pred.min(), pred.max()
                pred = (pred - lo) / (hi - lo).clamp_min(1e-8)
            small = (pred[0] * 255).round().clamp(0, 255).byte().cpu().numpy()
        return Image.fromarray(small, "L").resize(img.size, Image.LANCZOS)

    # -- full pipeline --------------------------------------------------------
    def process(self, img, processing, output, on_stage=None):
        """Run the configured pipeline on an RGB PIL image.

        Returns (result, crop_box); crop_box is the region of the input that was
        kept when auto-trim removed empty margins, otherwise None.
        """
        stage = on_stage or (lambda _text: None)
        model, device, precision = processing["model"], processing["device"], processing["precision"]
        if model == "colorkey":
            stage("Removing color…")
            key = None if processing["key_color_auto"] else _hex_rgb(processing["key_color"])
            colors, mask = color_key(img, key, processing["key_tolerance"], processing["key_softness"], processing["key_scope"])
            return self._finish(colors, mask, processing, output, stage, allow_matting=False)
        if not self.is_loaded(model, device, precision):
            if not weights_present(model):
                last = [-1]

                def progress(fraction):
                    percent = int(fraction * 100)
                    if percent != last[0]:
                        last[0] = percent
                        stage(f"Downloading {MODEL_NAMES[model]}… {percent}%")

                self.load(model, device, precision, on_progress=progress)
            else:
                stage("Loading model…")
                self.load(model, device, precision)
        stage("Removing background…")
        mask = self.predict_mask(img, model, device, precision)
        return self._finish(img, mask, processing, output, stage)

    @staticmethod
    def _finish(img, mask, processing, output, stage, allow_matting=True):
        """Apply the shared post-processing (threshold, matting, output mode, auto-trim) to a mask."""
        if processing["mask_threshold_enabled"]:
            cut = processing["mask_threshold"]
            mask = mask.point(lambda p: 255 if p > cut else 0)

        if output["mode"] == "mask":
            box = content_box(mask) if output["auto_trim"] else None
            return (mask.crop(box), box) if box else (mask, None)

        if processing["alpha_matting"] and allow_matting:
            stage("Refining edges…")
            cutout = alpha_matting_cutout(
                img,
                mask,
                processing["alpha_matting_foreground_threshold"],
                processing["alpha_matting_background_threshold"],
                processing["alpha_matting_erode_size"],
                processing["alpha_matting_base_size"],
            )
        else:
            cutout = img.copy()
            cutout.putalpha(mask)

        box = content_box(cutout.getchannel("A")) if output["auto_trim"] else None
        if box:
            cutout = cutout.crop(box)

        if output["mode"] == "color":
            flat = Image.new("RGB", cutout.size, output["background_color"])
            flat.paste(cutout, mask=cutout.getchannel("A"))
            return flat, box
        return cutout, box


def _hex_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def detect_key_color(arr):
    """Most common colour along the image border (coarsely binned, then averaged)."""
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]]).astype(np.int32)
    bins = border // 8
    codes = (bins[:, 0] << 10) | (bins[:, 1] << 5) | bins[:, 2]
    values, counts = np.unique(codes, return_counts=True)
    return border[codes == values[counts.argmax()]].mean(axis=0)


def color_key(img, key, tolerance, softness, scope):
    """Make one colour transparent (no AI). Works on the full-resolution image.

    tolerance / softness are percentages of the largest possible RGB distance:
    pixels within `tolerance` of the key become fully transparent, and the next
    `softness` fade back to opaque, which keeps anti-aliased edges smooth. Edge
    pixels have the key colour un-blended from them so no light fringe is left.
    scope "edges" only removes key-coloured areas connected to the image border.
    Returns (colours RGB image, alpha mask L image).
    """
    arr = np.asarray(img, dtype=np.float32)
    k = np.asarray(key if key is not None else detect_key_color(arr), dtype=np.float32)
    distance = np.sqrt(((arr - k) ** 2).sum(axis=2)) / (np.sqrt(3) * 255) * 100
    alpha = np.clip((distance - tolerance) / max(softness, 0.5), 0.0, 1.0)

    if scope == "edges":
        from scipy.ndimage import label

        labels, _ = label(alpha < 1.0)
        edge_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        alpha = np.where(np.isin(labels, edge_labels[edge_labels != 0]), alpha, 1.0)

    a = alpha[..., None]
    unblended = (arr - (1.0 - a) * k) / np.maximum(a, 1e-3)
    colors = np.where(a >= 1.0, arr, np.clip(unblended, 0, 255))
    return (
        Image.fromarray(colors.round().astype(np.uint8), "RGB"),
        Image.fromarray((alpha * 255).round().astype(np.uint8), "L"),
    )


def content_box(channel):
    """Bounding box of the visible part of an alpha/mask channel, or None if there is nothing to trim."""
    box = channel.point(lambda p: 255 if p > TRIM_ALPHA else 0).getbbox()
    if box is None or box == (0, 0) + channel.size:
        return None
    return box


def matting_available():
    try:
        import pymatting  # noqa: F401

        return True
    except Exception:
        return False


def alpha_matting_cutout(img, mask, foreground_threshold, background_threshold, erode_structure_size, base_size):
    """Closed-form alpha matting, as in backgroundremover.bg.alpha_matting_cutout."""
    from pymatting.alpha.estimate_alpha_cf import estimate_alpha_cf
    from pymatting.foreground.estimate_foreground_ml import estimate_foreground_ml
    from pymatting.util.util import stack_images
    from scipy.ndimage import binary_erosion

    size = img.size
    img = img.copy()
    img.thumbnail((base_size, base_size), Image.LANCZOS)
    mask = mask.resize(img.size, Image.LANCZOS)

    img = np.asarray(img)
    mask = np.asarray(mask)

    is_foreground = mask > foreground_threshold
    is_background = mask < background_threshold

    structure = None
    if erode_structure_size > 0:
        structure = np.ones((erode_structure_size, erode_structure_size), dtype=np.int64)

    is_foreground = binary_erosion(is_foreground, structure=structure)
    is_background = binary_erosion(is_background, structure=structure, border_value=1)

    # 0 = background, 128 = unknown, 255 = foreground
    trimap = np.full(mask.shape, dtype=np.uint8, fill_value=128)
    trimap[is_foreground] = 255
    trimap[is_background] = 0

    img_normalized = img / 255.0
    trimap_normalized = trimap / 255.0

    alpha = estimate_alpha_cf(img_normalized, trimap_normalized)
    foreground = estimate_foreground_ml(img_normalized, alpha)
    cutout = stack_images(foreground, alpha)

    cutout = np.clip(cutout * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(cutout).resize(size, Image.LANCZOS)
