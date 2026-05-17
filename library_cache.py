"""
library_cache.py — GWF clip metadata cache.

Replaces the serve.ps1 pattern of calling ffprobe on every
GET /api/library/list request.

Cache is stored in %USERPROFILE%/EdgeVideo/library_meta.json.
On startup:  scan GWF folder, probe any uncached files (background thread).
On new file: watchdog FileSystemEventHandler probes and caches automatically.
On delete:   cache entry is removed.
/api/library/list returns from cache in <10ms regardless of library size.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileDeletedEvent, FileMovedEvent
from watchdog.observers import Observer

log = logging.getLogger("edgevideo.cache")

# Video extensions to track
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}

# Module-level state (set by start())
_gwf_path: Optional[Path] = None
_cache_path: Optional[Path] = None
_cfg: dict = {}
_lock = threading.Lock()
_cache: dict = {}   # filename → metadata dict
_observer: Optional[Observer] = None


# ── Public API ─────────────────────────────────────────────────────────────────

def start(cfg: dict) -> None:
    """Initialise the cache and start the watchdog observer."""
    global _gwf_path, _cache_path, _cfg, _cache, _observer

    _cfg = cfg
    _gwf_path = Path(cfg.get("gwf_path", Path.home() / "EdgeVideo" / "gwf"))
    _gwf_path.mkdir(parents=True, exist_ok=True)
    _cache_path = _gwf_path.parent / "library_meta.json"

    _cache = _load_cache_file()

    # Background startup scan — don't block the server start
    threading.Thread(target=_startup_scan, daemon=True, name="cache-scan").start()

    # Watchdog — monitor GWF for new / deleted files
    _observer = Observer()
    _observer.schedule(_GWFHandler(), str(_gwf_path), recursive=False)
    _observer.start()
    log.info("Library cache started. GWF: %s", _gwf_path)


def stop() -> None:
    if _observer:
        _observer.stop()
        _observer.join(timeout=3)


def get_all() -> list[dict]:
    """Return list of clip metadata dicts, newest-modified first."""
    with _lock:
        items = list(_cache.values())
    items.sort(key=lambda x: x.get("modified", 0), reverse=True)
    return items


def get(filename: str) -> Optional[dict]:
    with _lock:
        return _cache.get(filename)


def probe_and_cache(fp: Path) -> None:
    """Run ffprobe on fp and store result in cache. Called on upload or new file."""
    if fp.suffix.lower() not in _VIDEO_EXTS:
        return
    meta = _probe(fp)
    with _lock:
        _cache[fp.name] = meta
    _save_cache_file()
    log.info("[Cache] + %s (%.1f MB, %.1fs)", fp.name, meta["size"] / 1e6, meta["duration"])


def invalidate(filename: str) -> None:
    """Remove a filename from cache (called on delete)."""
    with _lock:
        removed = _cache.pop(filename, None)
    if removed:
        _save_cache_file()
        log.info("[Cache] - %s", filename)


# ── Internal ───────────────────────────────────────────────────────────────────

def _startup_scan() -> None:
    """Probe any GWF files not already in cache."""
    if _gwf_path is None:
        return
    needs_probe = []
    for fp in _gwf_path.iterdir():
        if fp.suffix.lower() not in _VIDEO_EXTS:
            continue
        with _lock:
            cached = _cache.get(fp.name)
        # Re-probe if missing or file was modified after cache entry
        cached_at = cached.get("cached_at", 0) if cached else 0
        if not cached or fp.stat().st_mtime > cached_at:
            needs_probe.append(fp)

    if needs_probe:
        log.info("[Cache] Startup scan: probing %d uncached file(s)…", len(needs_probe))
    for fp in needs_probe:
        probe_and_cache(fp)
    if needs_probe:
        log.info("[Cache] Startup scan complete.")


def _probe(fp: Path) -> dict:
    """Run ffprobe and return metadata dict."""
    duration = 0.0
    ffprobe = _cfg.get("ffprobe_exe") or shutil.which("ffprobe")
    if ffprobe and Path(ffprobe).exists():
        try:
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_streams", str(fp)],
                capture_output=True, text=True, timeout=20,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    duration = float(stream.get("duration", 0))
                    break
        except Exception as exc:
            log.warning("[Cache] ffprobe failed for %s: %s", fp.name, exc)

    return {
        "name": fp.name,
        "size": fp.stat().st_size,
        "duration": duration,
        "modified": fp.stat().st_mtime,
        "cached_at": fp.stat().st_mtime,
    }


def _load_cache_file() -> dict:
    if _cache_path and _cache_path.exists():
        try:
            return json.loads(_cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("[Cache] Could not load library_meta.json: %s", exc)
    return {}


def _save_cache_file() -> None:
    if _cache_path is None:
        return
    try:
        with _lock:
            data = dict(_cache)
        _cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("[Cache] Could not save library_meta.json: %s", exc)


# ── Watchdog handler ───────────────────────────────────────────────────────────

class _GWFHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        fp = Path(event.src_path)
        if fp.suffix.lower() in _VIDEO_EXTS:
            # Brief delay so the file is fully written before probing
            threading.Timer(2.0, probe_and_cache, args=(fp,)).start()

    def on_deleted(self, event):
        if not event.is_directory:
            invalidate(Path(event.src_path).name)

    def on_moved(self, event):
        if not event.is_directory:
            # Old name removed, new name added
            invalidate(Path(event.src_path).name)
            fp = Path(event.dest_path)
            if fp.suffix.lower() in _VIDEO_EXTS:
                threading.Timer(0.5, probe_and_cache, args=(fp,)).start()
