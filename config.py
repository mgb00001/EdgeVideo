"""
config.py — EdgeVideo Console configuration loader / validator.

Loads console_config.json from %USERPROFILE%/EdgeVideo/.
Auto-generates the file with sensible defaults if it is missing.
Returns a warnings list so callers can surface problems without crashing.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

# ── Default locations ──────────────────────────────────────────────────────────
_USER = Path(os.environ.get("USERPROFILE", Path.home()))
_DATA_DIR = _USER / "EdgeVideo"
CONFIG_PATH = _DATA_DIR / "console_config.json"

# Known WinGet ffmpeg install glob (update if version changes)
_WINGET_FFMPEG_GLOB = (
    _USER
    / "AppData/Local/Microsoft/WinGet/Packages"
    / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
)


def _find_ffmpeg() -> str:
    """Return full path to ffmpeg.exe if detectable, else empty string."""
    # 1. Check WinGet install directory (most common on this machine)
    for candidate in _WINGET_FFMPEG_GLOB.parent.glob(
        "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-*/bin/ffmpeg.exe"
    ):
        if candidate.exists():
            return str(candidate)
    # 2. Check system PATH
    found = shutil.which("ffmpeg")
    return found or ""


def _find_ffprobe() -> str:
    """Return full path to ffprobe.exe, derived from ffmpeg path or PATH."""
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        probe = Path(ffmpeg).parent / "ffprobe.exe"
        if probe.exists():
            return str(probe)
    found = shutil.which("ffprobe")
    return found or ""


def _defaults() -> dict:
    gwf = str(_DATA_DIR / "gwf")
    sessions = str(_DATA_DIR / "sessions")
    log_file = str(_DATA_DIR / "console.log")
    ffmpeg = _find_ffmpeg()
    ffprobe = _find_ffprobe()
    comfy_env_ffmpeg = ffmpeg  # reuse same path for VHS

    return {
        "server_port": 8765,
        "gwf_path": gwf,
        "sessions_path": sessions,
        "project_dir": str(Path(__file__).parent),
        "ffmpeg_exe": ffmpeg,
        "ffprobe_exe": ffprobe,
        "ollama_port": 11434,
        "comfyui_port": 8188,
        "comfyui_python": r"C:\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe",
        "comfyui_main_dir": r"C:\ComfyUI\ComfyUI_windows_portable\ComfyUI",
        "comfyui_args": ["main.py", "--listen", "--enable-cors-header"],
        "comfyui_env": {
            "VHS_FORCE_FFMPEG_PATH": comfy_env_ffmpeg,
        },
        "open_browser_on_start": True,
        "log_file": log_file,
        "max_log_lines_gui": 500,
    }


def load() -> tuple[dict, list[str]]:
    """
    Load config from disk. Returns (config_dict, warnings_list).
    Creates the file with defaults if absent.
    Never raises — all errors are captured as warnings.
    """
    warnings: list[str] = []

    # Ensure data dir exists
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    cfg = _defaults()

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                on_disk = json.load(fh)
            # Merge: disk values override defaults (allows adding new keys later)
            cfg.update(on_disk)
        except json.JSONDecodeError as exc:
            warnings.append(f"console_config.json is invalid JSON ({exc}). Using defaults.")
        except OSError as exc:
            warnings.append(f"Cannot read console_config.json: {exc}. Using defaults.")
    else:
        # First run — write defaults
        save(cfg)
        warnings.append("console_config.json not found — created with auto-detected defaults.")

    warnings.extend(_validate(cfg))
    return cfg, warnings


def save(cfg: dict) -> None:
    """Write cfg to console_config.json (pretty-printed)."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


def _validate(cfg: dict) -> list[str]:
    """Return list of human-readable warnings for missing/invalid paths."""
    warnings: list[str] = []

    def _check_exe(key: str, label: str) -> None:
        val = cfg.get(key, "")
        if not val:
            warnings.append(f"{label} path not set in config ({key}).")
        elif not Path(val).exists():
            warnings.append(f"{label} not found at: {val}")

    _check_exe("ffmpeg_exe", "ffmpeg")
    _check_exe("ffprobe_exe", "ffprobe")
    _check_exe("comfyui_python", "ComfyUI Python")

    comfy_dir = cfg.get("comfyui_main_dir", "")
    if comfy_dir and not Path(comfy_dir).exists():
        warnings.append(f"ComfyUI main directory not found at: {comfy_dir}")

    for folder_key in ("gwf_path", "sessions_path"):
        p = cfg.get(folder_key, "")
        if p:
            Path(p).mkdir(parents=True, exist_ok=True)

    return warnings
