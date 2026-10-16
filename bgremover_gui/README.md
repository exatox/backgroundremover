# Background Remover GUI

A local, browser-based interface for this repository's U²-Net background remover.

## Setup (once)

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1        # add -Cpu on a machine without an NVIDIA GPU
```

This creates `.venv`, installs the pinned dependencies and builds `BackgroundRemover.exe`.

## Use

Double-click `BackgroundRemover.exe`. It starts a small server bound to `127.0.0.1` and opens the
page in your default browser. The server exits a few seconds after the last tab is closed (or when
you press the power button in the sidebar). Launching the exe again while it is running just opens
another tab.

- **Add images**: drag and drop files or folders, paste with `Ctrl+V`, or browse.
- **Batch**: everything added is queued and processed in order; "Download all" gives a `.zip`.
- **Auto-grab**: the Screenshots and Downloads toggles queue any new image that appears in those
  folders while the app is open (Snipping Tool captures land in Screenshots). Files already there
  when a toggle is switched on are ignored, and the app never re-queues its own results.
- **Auto-trim**: crops each result to its subject. "Trim empty space" on a card does the same to an
  existing result, in place.
- **Models**: General (u2net), People, Lightweight, and **High detail (BiRefNet)**, which handles
  cables, hair and background showing through gaps in the subject far better. BiRefNet's weights
  (444 MB) are downloaded on first use from Hugging Face at a pinned commit and checked against a
  SHA-256 before loading.
- **Color key** (no AI): removes one color, auto-detected from the image edges or picked with the
  eyedropper that appears on finished images when Auto is off. Best for drawings, diagrams and
  screenshots on a plain background; keeps the original pixels at full resolution.
- **Precision** (BiRefNet on the GPU): Half or Full. The U²-Net models always run at full precision,
  because their masks break down in half precision.
- **Free GPU memory when idle**: the model is released after the chosen idle time and reloads by
  itself on the next image. Only one model is kept in memory at a time.
- **Hover actions**: copy, download, show in folder, re-process with the current settings, trim.
- **Results**: click a card for the before/after viewer. Copy to the clipboard, download, drag the
  image out into another app, or show the file in Explorer.
- **History**: every processed image whose output file still exists. Files deleted or moved outside
  the app drop off the list; deleting in the app sends the file to the Recycle Bin.
- **Settings**: saved to `settings.yaml` in the project folder as soon as they change.

## Layout

| Path | Purpose |
| --- | --- |
| `bgremover_gui/` | Server (`server.py`), queue and state (`app.py`), inference (`engine.py`), settings, history |
| `bgremover_gui/web/` | The page: `index.html`, `app.css`, `app.js` |
| `launcher/` | Source of `BackgroundRemover.exe` and the icon generator |
| `settings.yaml` | Your settings (created on first run) |
| `output/` | Default output folder |
| `app_data/` | History index, kept originals, thumbnails, assembled model weights, `app.log` |

## Notes

- The exe is a thin launcher for `.venv\Scripts\pythonw.exe -m bgremover_gui`; it has to stay in the
  project folder.
- The server only accepts requests carrying the per-launch token embedded in the page, and checks
  the `Host` and `Origin` headers, so other sites open in the browser cannot call it.
- Model weights are assembled from `models/` (or downloaded, for BiRefNet) and verified by SHA-256
  before loading. BiRefNet's network code is a trimmed port in `bgremover_gui/birefnet.py` (MIT), so
  no code is downloaded or executed at runtime, and its weights are read from a `.safetensors` file,
  which holds only data.
- Run `python -m bgremover_gui --no-browser` from the venv to start without opening a tab.
