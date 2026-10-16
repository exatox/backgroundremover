import json
import logging
import os
import sys
import threading
import urllib.request
import webbrowser

from .paths import APP_DIR, INSTANCE_PATH, LOG_PATH, ensure_dirs


def _setup_logging():
    try:
        if LOG_PATH.stat().st_size > 2 * 1024 * 1024:
            LOG_PATH.unlink()
    except OSError:
        pass
    stream = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    # pythonw has no console: route stray prints and tracebacks to the log too.
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        sys.stdout = sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _running_instance():
    """Return the URL of an already running instance, if any."""
    try:
        with open(INSTANCE_PATH, "r", encoding="utf-8") as f:
            port = int(json.load(f)["port"])
        url = f"http://127.0.0.1:{port}/"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "api/ping", timeout=1.5) as resp:
            if json.load(resp).get("app") == "bgremover-gui":
                return url
    except Exception:
        pass
    return None


def main():
    os.chdir(APP_DIR)
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    ensure_dirs()
    no_browser = "--no-browser" in sys.argv

    _setup_logging()
    log = logging.getLogger("bgremover")

    existing = _running_instance()
    if existing:
        if not no_browser:
            webbrowser.open(existing)
        return

    from .app import App
    from .server import Server

    app = App()
    port = app.settings.get()["app"]["port"]
    try:
        server = Server(("127.0.0.1", port), app)
    except OSError:
        log.warning("Port %s is busy, using a free one instead", port)
        server = Server(("127.0.0.1", 0), app)

    with open(INSTANCE_PATH, "w", encoding="utf-8") as f:
        json.dump({"port": server.port, "pid": os.getpid()}, f)

    url = f"http://127.0.0.1:{server.port}/"
    log.info("Serving on %s", url)
    threading.Thread(target=server.watch_tabs, name="tab-watcher", daemon=True).start()
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.quit("interrupted")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.getLogger("bgremover").exception("Startup failed")
        raise
