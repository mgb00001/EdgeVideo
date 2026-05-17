"""
tray.py — EdgeVideo system tray icon.

The tray icon lives in the Windows notification area.
Right-click menu provides all console actions.
"Open Dashboard" opens http://localhost:8765/dashboard in the browser
(browser-based dashboard — no Tkinter window needed).

Tkinter is NOT used here. The hidden Tk root in console.py exists
solely for tkinter.filedialog (Save As dialog).
"""

import logging
import os
import threading
import tkinter.messagebox as mb
import webbrowser
from pathlib import Path
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

log = logging.getLogger("edgevideo.tray")

# Module-level refs set by start_tray()
_cfg: dict = {}
_pm = None
_root = None        # Tkinter root — used only for mb.askyesno (quit confirm)
_shutdown_cb: Optional[Callable] = None
_icon: Optional[pystray.Icon] = None


# ── Icon image generation ──────────────────────────────────────────────────────

def _make_icon(color: str) -> Image.Image:
    """Generate a 64×64 RGBA icon: dark background with a coloured status dot."""
    img = Image.new("RGBA", (64, 64), (20, 20, 30, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], outline=(80, 80, 80, 200), width=2)
    palette = {
        "green": (34, 200, 90),
        "amber": (232, 160, 32),
        "red":   (232, 80,  80),
    }
    fill = palette.get(color, palette["amber"])
    draw.ellipse([10, 10, 54, 54], fill=fill + (255,))
    return img


_ICON_GREEN = _make_icon("green")
_ICON_AMBER = _make_icon("amber")
_ICON_RED   = _make_icon("red")


def _icon_for_status(snap: dict) -> Image.Image:
    comfy_ok  = snap.get("comfyui", {}).get("ok", False)
    ffmpeg_ok = snap.get("ffmpeg",  {}).get("ok", False)
    if not ffmpeg_ok:
        return _ICON_RED
    if not comfy_ok:
        return _ICON_AMBER
    return _ICON_GREEN


# ── Menu builder ───────────────────────────────────────────────────────────────

def _build_menu() -> pystray.Menu:

    def _comfy_label(item):
        try:
            ok = _pm.check_port(_cfg.get("comfyui_port", 8188))
        except Exception:
            ok = False
        return f"ComfyUI: {'RUNNING ✓' if ok else 'STOPPED ✗'}"

    def _ollama_label(item):
        try:
            ok = _pm.check_port(_cfg.get("ollama_port", 11434))
        except Exception:
            ok = False
        return f"Ollama: {'RUNNING ✓' if ok else 'STOPPED'} (auto)"

    return pystray.Menu(
        pystray.MenuItem("EdgeVideo Console v4.0", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Dashboard",          _on_open_dashboard),
        pystray.MenuItem("Open Browser",            _on_open_browser),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_comfy_label,  None, enabled=False),
        pystray.MenuItem(_ollama_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart ComfyUI",         _on_restart_comfyui),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open GWF Folder",         _on_open_gwf),
        pystray.MenuItem("Open Sessions Folder",    _on_open_sessions),
        pystray.MenuItem("View Log File",           _on_view_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit EdgeVideo",          _on_quit),
    )


# ── Menu callbacks ─────────────────────────────────────────────────────────────

def _on_open_dashboard(icon, item):
    port = _cfg.get("server_port", 8765)
    webbrowser.open(f"http://localhost:{port}/dashboard")

def _on_open_browser(icon, item):
    port = _cfg.get("server_port", 8765)
    webbrowser.open(f"http://localhost:{port}/EdgeVideo_Gemma4.html")

def _on_restart_comfyui(icon, item):
    def _do():
        log.info("ComfyUI restart requested from tray menu.")
        result = _pm.restart_comfyui()
        log.info("ComfyUI restart: %s", result.get("message", ""))
    threading.Thread(target=_do, daemon=True).start()

def _on_open_gwf(icon, item):
    gwf = _cfg.get("gwf_path", "")
    if gwf:
        os.startfile(gwf)

def _on_open_sessions(icon, item):
    sess = _cfg.get("sessions_path", "")
    if sess:
        os.startfile(sess)

def _on_view_log(icon, item):
    log_file = _cfg.get("log_file", "")
    if log_file and Path(log_file).exists():
        os.startfile(log_file)

def _on_quit(icon, item):
    # Show confirm dialog on the main thread via Tkinter
    if _root:
        _root.after(0, _confirm_quit)
    else:
        _do_quit()

def _confirm_quit():
    if mb.askyesno("Quit EdgeVideo",
                   "Stop the EdgeVideo Console?\n\nThis will shut down the HTTP server.",
                   parent=_root):
        log.info("User quit from tray menu.")
        _do_quit()

def _do_quit():
    if _icon:
        _icon.stop()
    if _shutdown_cb:
        _shutdown_cb()


# ── Status change callback (called by ProcessManager health loop) ──────────────

def _on_pm_status_change(snap: dict) -> None:
    if _icon:
        _icon.icon = _icon_for_status(snap)


# ── Public entry point ─────────────────────────────────────────────────────────

def start_tray(cfg: dict, pm, root, shutdown_cb: Callable) -> None:
    global _cfg, _pm, _root, _shutdown_cb, _icon

    _cfg = cfg
    _pm = pm
    _root = root
    _shutdown_cb = shutdown_cb

    # Register health-change callback
    pm._on_status_change = _on_pm_status_change

    _icon = pystray.Icon(
        name="EdgeVideo",
        icon=_ICON_AMBER,
        title="EdgeVideo Console — click to open dashboard",
        menu=_build_menu(),
    )
    _icon.run_detached()
    log.info("System tray icon started.")
