"""
console.py — EdgeVideo Management Console, main entry point.

Startup sequence:
  1. Load / generate config
  2. Configure rotating log file
  3. Create hidden Tkinter root (needed for file dialogs + dashboard)
  4. Start Flask HTTP server in daemon thread
  5. Start ProcessManager health check loop in daemon thread
  6. Start pystray tray icon (detached — its own thread)
  7. Open browser if configured
  8. Block on Tkinter mainloop()
  9. On shutdown: stop Flask, stop health loop, destroy Tk
"""

import logging
import logging.handlers
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

# ── Bootstrap path so sibling modules import correctly ───────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg_module
import process_manager as pm_module

# ── Globals shared across modules ─────────────────────────────────────────────
# These are set during startup and read by server.py / tray.py.
CFG: dict = {}
PM: pm_module.ProcessManager = None   # type: ignore[assignment]
ROOT: tk.Tk = None                    # type: ignore[assignment]
LOG_QUEUE: queue.Queue = queue.Queue(maxsize=2000)
_shutdown_event = threading.Event()

# ── Logging setup ──────────────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    """Emit log records to LOG_QUEUE for the dashboard / SSE stream."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            LOG_QUEUE.put_nowait(self.format(record))
        except queue.Full:
            pass


def _setup_logging(log_file: str) -> None:
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
                            datefmt="%H:%M:%S")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Rotating file handler
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)
    except OSError as exc:
        print(f"[WARN] Could not open log file {log_file}: {exc}")

    # Queue handler (feeds dashboard + SSE)
    qh = _QueueHandler()
    qh.setFormatter(fmt)
    root_logger.addHandler(qh)

    # Console (stderr) for dev convenience — suppress in production if desired
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    root_logger.addHandler(ch)


# ── Flask server thread ────────────────────────────────────────────────────────

def _start_flask() -> None:
    import server as srv_module
    srv_module.create_app(CFG, PM, ROOT, LOG_QUEUE).run(
        host="127.0.0.1",
        port=CFG.get("server_port", 8765),
        threaded=True,
        use_reloader=False,
    )


# ── Tkinter dialog bridge (used by server.py for Save As) ─────────────────────
# server.py posts (token, swf_path, proj_name) tuples here;
# the Tkinter pump picks them up and runs the dialog on the main thread.

DIALOG_REQUESTS: queue.Queue = queue.Queue()
DIALOG_RESULTS: dict = {}          # token → result dict
_dialog_lock = threading.Lock()


def _pump_dialogs() -> None:
    """Called by root.after — drain dialog request queue on main thread."""
    try:
        while True:
            token, swf_path, proj_name = DIALOG_REQUESTS.get_nowait()
            _run_save_dialog(token, swf_path, proj_name)
    except queue.Empty:
        pass
    if ROOT and ROOT.winfo_exists():
        ROOT.after(50, _pump_dialogs)


def _run_save_dialog(token: str, swf_path: str, proj_name: str) -> None:
    import tkinter.filedialog as fd
    import shutil

    # Find the source mp4
    swf = Path(swf_path)
    src = swf / f"{proj_name}.mp4"
    if not src.exists():
        mp4s = list(swf.glob("*.mp4"))
        src = mp4s[0] if mp4s else None

    if src is None:
        with _dialog_lock:
            DIALOG_RESULTS[token] = {"ok": False, "message": "Output file not found."}
        return

    # Use a temporary always-on-top Toplevel as the dialog parent.
    # parent=ROOT (a withdrawn window) causes the dialog to return "" immediately
    # on Windows without ever appearing on screen.
    helper = tk.Toplevel(ROOT)
    helper.withdraw()
    helper.wm_attributes("-topmost", True)
    helper.deiconify()
    helper.update()

    dest = fd.asksaveasfilename(
        parent=helper,
        title="Save compilation as…",
        initialfile=f"{proj_name}.mp4",
        initialdir=str(Path.home() / "Videos"),
        defaultextension=".mp4",
        filetypes=[("MP4 video", "*.mp4")],
    )
    helper.destroy()
    if not dest:
        with _dialog_lock:
            DIALOG_RESULTS[token] = {"ok": False, "cancelled": True}
        return

    try:
        shutil.copy2(str(src), dest)
        log = logging.getLogger("edgevideo.dialog")
        log.info("Saved As: %s → %s", src.name, dest)
        with _dialog_lock:
            DIALOG_RESULTS[token] = {"ok": True, "path": dest}
    except OSError as exc:
        with _dialog_lock:
            DIALOG_RESULTS[token] = {"ok": False, "message": str(exc)}


# ── Shutdown ───────────────────────────────────────────────────────────────────

def shutdown() -> None:
    """Graceful shutdown — called from tray 'Quit' or Tkinter window close."""
    log = logging.getLogger("edgevideo")
    log.info("Shutting down EdgeVideo Console…")
    _shutdown_event.set()
    if PM:
        PM.stop()
    try:
        import library_cache as lc
        lc.stop()
    except Exception:
        pass
    try:
        import server as srv_module
        func = getattr(srv_module, "shutdown_server", None)
        if func:
            func()
    except Exception:
        pass
    if ROOT and ROOT.winfo_exists():
        ROOT.quit()
        ROOT.destroy()
    # pystray icon stopped from tray.py after this returns


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    global CFG, PM, ROOT

    # 1. Load config
    CFG, warnings = cfg_module.load()

    # 2. Logging
    _setup_logging(CFG.get("log_file", str(Path.home() / "EdgeVideo" / "console.log")))
    log = logging.getLogger("edgevideo")
    log.info("=" * 60)
    log.info("EdgeVideo Management Console starting…")
    log.info("Python %s | port %s", sys.version.split()[0], CFG.get("server_port", 8765))
    for w in warnings:
        log.warning("Config: %s", w)

    # 3. Hidden Tkinter root (never shown — just hosts dialogs + dashboard Toplevel)
    ROOT = tk.Tk()
    ROOT.withdraw()  # keep hidden
    ROOT.title("EdgeVideo Console")
    ROOT.protocol("WM_DELETE_WINDOW", lambda: None)  # tray owns quit

    # 4. Start Flask in daemon thread
    flask_thread = threading.Thread(target=_start_flask, daemon=True, name="flask")
    flask_thread.start()
    log.info("Flask server started on port %s", CFG.get("server_port", 8765))

    # 5. Start ProcessManager
    PM = pm_module.ProcessManager(CFG)
    PM.start()

    # 5b. Start library cache (background scan + watchdog)
    import library_cache as lc
    lc.start(CFG)
    log.info("Library cache started.")

    # 6. Start pystray tray (must happen after PM and Flask are ready)
    import tray as tray_module
    tray_module.start_tray(CFG, PM, ROOT, shutdown)

    # 7. Open browser
    if CFG.get("open_browser_on_start", True):
        port = CFG.get("server_port", 8765)
        url = f"http://localhost:{port}/EdgeVideo_Gemma4.html"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        log.info("Browser will open: %s", url)

    # 8. Start dialog pump
    ROOT.after(50, _pump_dialogs)

    # 9. Block on Tkinter mainloop
    log.info("Tkinter mainloop starting (main thread).")
    try:
        ROOT.mainloop()
    except KeyboardInterrupt:
        pass

    log.info("EdgeVideo Console exited.")


if __name__ == "__main__":
    main()
