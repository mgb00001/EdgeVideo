"""
server.py — EdgeVideo Flask HTTP server.

Ported from serve.ps1 (PowerShell HttpListener).
All routes are identical in URL and JSON shape — the browser HTML
requires no changes to work with this server.

New routes added:
  GET  /api/status           — service health + disk usage
  POST /api/start-service    — start comfyui
  POST /api/stop-service     — stop comfyui
  GET  /api/session/:id/download  — download MP4 as browser attachment
  GET  /api/save-as-status/:token — poll Save As dialog result (legacy)
  GET  /api/log-stream       — SSE live log tail
  GET  /api/config           — read config
  POST /api/config           — write config
"""

import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, stream_with_context

log = logging.getLogger("edgevideo.server")

# Module-level refs set by create_app()
_cfg: dict = {}
_pm = None          # ProcessManager
_root = None        # Tkinter root (for dialog dispatch)
_log_queue = None   # queue.Queue of log line strings

# Save As token store
_sa_results: dict = {}
_sa_lock = threading.Lock()

# ── App factory ───────────────────────────────────────────────────────────────

def create_app(cfg: dict, pm, root, log_queue: queue.Queue) -> Flask:
    global _cfg, _pm, _root, _log_queue
    _cfg = cfg
    _pm = pm
    _root = root
    _log_queue = log_queue

    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB upload limit

    # CORS — allow browser on same machine
    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type,X-Filename"
        return resp

    @app.before_request
    def _log_req():
        request._start = time.monotonic()

    @app.after_request
    def _log_resp(resp):
        dur = int((time.monotonic() - getattr(request, "_start", time.monotonic())) * 1000)
        if request.path not in ("/api/log-stream",):
            log.info("%s %s %s %dms", request.method, request.path, resp.status_code, dur)
        return resp

    _register_routes(app)
    return app


def shutdown_server() -> None:
    """Called from console.py during graceful shutdown."""
    func = _shutdown_func.get("fn")
    if func:
        func()

_shutdown_func: dict = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(data: dict, status: int = 200):
    return jsonify(data), status


def _gwf() -> Path:
    return Path(_cfg.get("gwf_path", Path.home() / "EdgeVideo" / "gwf"))


def _sess_dir() -> Path:
    return Path(_cfg.get("sessions_path", Path.home() / "EdgeVideo" / "sessions"))


def _swf(sid: str) -> Path:
    return _sess_dir() / sid


def _send_range(file_path: Path):
    """Stream a file with HTTP 206 byte-range support (required for <video> seeking)."""
    if not file_path.exists():
        return _json({"ok": False, "message": "File not found"}, 404)

    total = file_path.stat().st_size
    range_hdr = request.headers.get("Range")
    start = 0
    end = total - 1

    if range_hdr:
        m = re.match(r"bytes=(\d*)-(\d*)", range_hdr)
        if m:
            s, e = m.group(1), m.group(2)
            if s:
                start = int(s)
            if e:
                end = int(e)
            if end >= total:
                end = total - 1
            if start > end or start >= total:
                return Response(
                    status=416,
                    headers={"Content-Range": f"bytes */{total}"},
                )

    length = end - start + 1
    ext = file_path.suffix.lower()
    mime_map = {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".html": "text/html; charset=utf-8", ".js": "application/javascript",
        ".css": "text/css", ".json": "application/json",
    }
    content_type = mime_map.get(ext, "application/octet-stream")

    def _generate():
        with open(file_path, "rb") as fh:
            fh.seek(start)
            remaining = length
            buf_size = 65536
            while remaining > 0:
                chunk = fh.read(min(buf_size, remaining))
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)

    status = 206 if range_hdr else 200
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
    }
    if range_hdr:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"

    return Response(
        stream_with_context(_generate()),
        status=status,
        headers=headers,
        direct_passthrough=True,
    )


# ── Route registration ────────────────────────────────────────────────────────

def _register_routes(app: Flask) -> None:

    @app.route("/", methods=["OPTIONS"])
    @app.route("/<path:p>", methods=["OPTIONS"])
    def _options(p=""):
        return "", 204

    # ── GET /dashboard — browser-based management console ─────────────────────
    @app.route("/dashboard")
    def _dashboard():
        return Response(_DASHBOARD_HTML, content_type="text/html; charset=utf-8")

    # ── Static file serving ───────────────────────────────────────────────────
    @app.route("/")
    def _index():
        return _static_file("EdgeVideo_Gemma4.html")

    @app.route("/<path:filename>")
    def _static(filename):
        return _static_file(filename)

    def _static_file(filename):
        project_dir = Path(_cfg.get("project_dir", Path(__file__).parent))
        fp = project_dir / filename
        if fp.is_file():
            ext = fp.suffix.lower()
            mime_map = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript",
                ".css": "text/css",
                ".json": "application/json",
                ".png": "image/png",
                ".ico": "image/x-icon",
            }
            mime = mime_map.get(ext, "application/octet-stream")
            return send_file(fp, mimetype=mime)
        # Fallback to index
        idx = project_dir / "EdgeVideo_Gemma4.html"
        return send_file(idx, mimetype="text/html; charset=utf-8")

    # ── GET /api/workspace/info ───────────────────────────────────────────────
    @app.route("/api/workspace/info")
    def _workspace_info():
        return _json({"ok": True, "gwf": str(_gwf()), "sessDir": str(_sess_dir())})

    # ── POST /api/library/upload ──────────────────────────────────────────────
    @app.route("/api/library/upload", methods=["POST"])
    def _library_upload():
        fn = request.headers.get("X-Filename", "")
        if not fn:
            return _json({"ok": False, "message": "X-Filename header missing"}, 400)
        fn = Path(fn).name
        dest = _gwf() / fn
        _gwf().mkdir(parents=True, exist_ok=True)
        try:
            with open(dest, "wb") as fh:
                shutil.copyfileobj(request.stream, fh)
            sz = dest.stat().st_size
            # Probe duration via ffprobe (or return 0 — cache will fill it in later)
            dur = _probe_duration(dest)
            log.info("[GWF] + %s (%.1f MB)", fn, sz / 1e6)
            # Notify library cache
            _notify_cache_new(dest)
            return _json({"ok": True, "name": fn, "size": sz, "duration": dur})
        except OSError as exc:
            return _json({"ok": False, "message": str(exc)}, 500)

    # ── GET /api/library/list ─────────────────────────────────────────────────
    @app.route("/api/library/list")
    def _library_list():
        try:
            import library_cache as lc
            files = lc.get_all()
        except Exception:
            # Fallback: scan without cache
            files = []
            exts = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
            for f in sorted(_gwf().glob("*"), key=lambda x: -x.stat().st_mtime):
                if f.suffix.lower() in exts:
                    files.append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "duration": 0,
                        "modified": f.stat().st_mtime,
                    })
        return _json({"ok": True, "files": files})

    # ── GET /api/library/serve ────────────────────────────────────────────────
    @app.route("/api/library/serve")
    def _library_serve():
        n = request.args.get("name", "")
        fp = _gwf() / Path(n).name
        return _send_range(fp)

    # ── DELETE /api/library/remove ────────────────────────────────────────────
    @app.route("/api/library/remove", methods=["DELETE"])
    def _library_remove():
        n = request.args.get("name", "")
        fp = _gwf() / Path(n).name
        if fp.exists():
            fp.unlink()
            _notify_cache_remove(fp)
        return _json({"ok": True})

    # ── POST /api/session/create ──────────────────────────────────────────────
    @app.route("/api/session/create", methods=["POST"])
    def _session_create():
        import random, string, datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        sid = f"session_{ts}_{rnd}"
        swf = _swf(sid)
        swf.mkdir(parents=True, exist_ok=True)
        log.info("[Session] Created: %s", sid)
        return _json({"ok": True, "sessionId": sid, "swfPath": str(swf)})

    # ── GET /api/session/list ─────────────────────────────────────────────────
    @app.route("/api/session/list")
    def _session_list():
        sess = _sess_dir()
        sess.mkdir(parents=True, exist_ok=True)
        sessions = []
        for d in sorted(sess.iterdir(), key=lambda x: -x.stat().st_mtime):
            if d.is_dir():
                sessions.append(_session_meta(d))
        return _json({"ok": True, "sessions": sessions})

    def _session_meta(d: Path) -> dict:
        state_file = d / "state.json"
        out_file = d / "compilation.mp4"
        thumb_file = d / "thumbnail.jpg"
        state = {}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        mp4s = list(d.glob("*.mp4"))
        out_size = 0
        has_out = out_file.exists()
        if not has_out and mp4s:
            out_file = mp4s[0]
            has_out = True
        if has_out:
            out_size = out_file.stat().st_size
        return {
            "id": d.name,
            "created": d.stat().st_ctime,
            "modified": d.stat().st_mtime,
            "hasOutput": has_out,
            "hasThumbnail": thumb_file.exists(),
            "outputSize": out_size,
            "projName": state.get("projName", d.name),
            "clipCount": state.get("clipCount", 0),
            "duration": state.get("totalDur", 0),
            "quality": state.get("expQ", ""),
        }

    # ── POST /api/session/:id/save-asset ─────────────────────────────────────
    @app.route("/api/session/<sid>/save-asset", methods=["POST"])
    def _save_asset(sid):
        fn = request.headers.get("X-Filename", "")
        if not fn:
            return _json({"ok": False, "message": "X-Filename header missing"}, 400)
        fn = Path(fn).name
        swf = _swf(sid)
        swf.mkdir(parents=True, exist_ok=True)
        dest = swf / fn
        try:
            with open(dest, "wb") as fh:
                shutil.copyfileobj(request.stream, fh)
            sz = dest.stat().st_size
            log.info("[SWF %s] + %s (%.0f KB)", sid, fn, sz / 1024)
            return _json({"ok": True, "name": fn, "size": sz})
        except OSError as exc:
            return _json({"ok": False, "message": str(exc)}, 500)

    # ── POST /api/session/:id/state ───────────────────────────────────────────
    @app.route("/api/session/<sid>/state", methods=["POST"])
    def _state_post(sid):
        swf = _swf(sid)
        swf.mkdir(parents=True, exist_ok=True)
        body = request.get_data(as_text=True)
        try:
            (swf / "state.json").write_text(body, encoding="utf-8")
            return _json({"ok": True})
        except OSError as exc:
            return _json({"ok": False, "message": str(exc)}, 500)

    # ── GET /api/session/:id/state ────────────────────────────────────────────
    @app.route("/api/session/<sid>/state")
    def _state_get(sid):
        sf = _swf(sid) / "state.json"
        if sf.exists():
            return Response(sf.read_bytes(), content_type="application/json")
        return _json({"message": "state not found"}, 404)

    # ── GET /api/session/:id/thumbnail ───────────────────────────────────────
    @app.route("/api/session/<sid>/thumbnail")
    def _thumbnail(sid):
        tf = _swf(sid) / "thumbnail.jpg"
        if tf.exists():
            return send_file(tf, mimetype="image/jpeg")
        return _json({"message": "not found"}, 404)

    # ── GET /api/session/:id/serve ────────────────────────────────────────────
    @app.route("/api/session/<sid>/serve")
    def _session_serve(sid):
        n = request.args.get("name", "")
        fp = _swf(sid) / Path(n).name
        return _send_range(fp)

    # ── POST /api/session/:id/export ─────────────────────────────────────────
    @app.route("/api/session/<sid>/export", methods=["POST"])
    def _export(sid):
        swf = _swf(sid)
        swf.mkdir(parents=True, exist_ok=True)
        try:
            body = request.get_json(force=True) or {}
            script_content = body.get("script", "")
            proj_name = body.get("projName", "compilation")
            job = _pm.start_export(sid, script_content, proj_name, str(swf))
            return _json({"ok": True, "sessionId": sid, "outputFile": f"{proj_name}.mp4"})
        except Exception as exc:
            log.error("[Export %s] Failed: %s", sid, exc)
            return _json({"ok": False, "message": str(exc)}, 500)

    # ── GET /api/session/:id/export-status ────────────────────────────────────
    @app.route("/api/session/<sid>/export-status")
    def _export_status(sid):
        result = _pm.get_export_status(sid)
        if result is None:
            return _json({"status": "not_found"}, 404)
        return _json(result)

    # ── GET /api/session/:id/output ───────────────────────────────────────────
    @app.route("/api/session/<sid>/output")
    def _output(sid):
        swf = _swf(sid)
        # Try proj_name from job first, then scan
        pm_result = _pm.get_export_status(sid) if _pm else None
        fp = None
        if pm_result and pm_result.get("outputFile"):
            fp = swf / pm_result["outputFile"]
        if not fp or not fp.exists():
            mp4s = list(swf.glob("*.mp4"))
            fp = mp4s[0] if mp4s else None
        if not fp:
            return _json({"ok": False, "message": "Output not found"}, 404)
        return _send_range(fp)

    # ── POST /api/session/:id/play (external player — Archive tab) ────────────
    @app.route("/api/session/<sid>/play", methods=["POST"])
    def _play(sid):
        swf = _swf(sid)
        mp4s = list(swf.glob("*.mp4"))
        if not mp4s:
            return _json({"ok": False, "message": "Output not found"}, 404)
        fp = mp4s[0]
        try:
            os.startfile(str(fp))
            log.info("[Session %s] Playing externally: %s", sid, fp.name)
            return _json({"ok": True})
        except Exception as exc:
            return _json({"ok": False, "message": str(exc)}, 500)

    # ── GET /api/session/:id/download ────────────────────────────────────────
    # Streams the compiled MP4 to the browser as an attachment download.
    # The browser shows its own native Save dialog — no Tkinter required.
    @app.route("/api/session/<sid>/download")
    def _download(sid):
        swf = _swf(sid)
        mp4s = list(swf.glob("*.mp4"))
        if not mp4s:
            return _json({"ok": False, "message": "Output not found"}, 404)
        fp = mp4s[0]
        log.info("[Session %s] Download: %s", sid, fp.name)
        return send_file(
            str(fp),
            as_attachment=True,
            download_name=fp.name,
            mimetype="video/mp4",
        )

    # ── POST /api/session/:id/save-as ─────────────────────────────────────────
    # Non-blocking: returns a token immediately; browser polls /api/save-as-status/:token
    @app.route("/api/session/<sid>/save-as", methods=["POST"])
    def _save_as(sid):
        swf = _swf(sid)
        mp4s = list(swf.glob("*.mp4"))
        proj_name = mp4s[0].stem if mp4s else "compilation"

        token = str(uuid.uuid4())[:8]

        # Post dialog request to the Tkinter main thread via console.py's queue
        try:
            import console as con
            con.DIALOG_REQUESTS.put_nowait((token, str(swf), proj_name))
        except Exception as exc:
            return _json({"ok": False, "message": f"Dialog bridge error: {exc}"}, 500)

        return _json({"ok": True, "token": token})

    # ── GET /api/save-as-status/:token ───────────────────────────────────────
    @app.route("/api/save-as-status/<token>")
    def _save_as_status(token):
        import console as con
        with con._dialog_lock:
            result = con.DIALOG_RESULTS.get(token)
        if result is None:
            return _json({"done": False})
        # Clean up after delivery
        with con._dialog_lock:
            con.DIALOG_RESULTS.pop(token, None)
        return _json({**result, "done": True})

    # ── DELETE /api/session/:id ───────────────────────────────────────────────
    @app.route("/api/session/<sid>", methods=["DELETE"])
    def _session_delete(sid):
        swf = _swf(sid)
        try:
            if swf.exists():
                shutil.rmtree(str(swf), ignore_errors=False)
            _pm.remove_job(sid)
            log.info("[Session %s] Deleted", sid)
            return _json({"ok": True})
        except OSError as exc:
            log.error("[Session %s] Delete failed: %s", sid, exc)
            return _json({"ok": False,
                          "message": f"Delete failed (file may be open): {exc}"}, 500)

    # ── POST /api/restart-comfyui ─────────────────────────────────────────────
    @app.route("/api/restart-comfyui", methods=["POST"])
    def _restart_comfyui():
        log.info("[API] ComfyUI restart requested")
        result = _pm.restart_comfyui()
        status = 200 if result.get("ok") else 500
        return _json(result, status)

    # ── GET /api/comfyui-status ───────────────────────────────────────────────
    @app.route("/api/comfyui-status")
    def _comfyui_status():
        running = _pm.check_port(_cfg.get("comfyui_port", 8188))
        return _json({"running": running})

    # ── GET /api/status ───────────────────────────────────────────────────────
    @app.route("/api/status")
    def _status():
        snap = _pm.get_status_snapshot()
        ollama_ok = snap["ollama"]["ok"]
        comfy_ok  = snap["comfyui"]["ok"]
        ffmpeg_ok = snap["ffmpeg"]["ok"]
        return _json({
            "server":  {"ok": True, "port": _cfg.get("server_port", 8765)},
            "ollama":  {"ok": ollama_ok,  "port": _cfg.get("ollama_port", 11434)},
            "comfyui": {"ok": comfy_ok,   "port": _cfg.get("comfyui_port", 8188)},
            "ffmpeg":  {"ok": ffmpeg_ok,  "path": snap["ffmpeg"].get("path", "")},
            "disk":    snap["disk"],
        })

    # ── POST /api/start-service ───────────────────────────────────────────────
    @app.route("/api/start-service", methods=["POST"])
    def _start_service():
        body = request.get_json(force=True) or {}
        svc = body.get("service", "")
        if svc == "comfyui":
            return _json(_pm.start_comfyui())
        return _json({"ok": False, "message": f"Unknown service: {svc}"}, 400)

    # ── POST /api/stop-service ────────────────────────────────────────────────
    @app.route("/api/stop-service", methods=["POST"])
    def _stop_service():
        body = request.get_json(force=True) or {}
        svc = body.get("service", "")
        if svc == "comfyui":
            return _json(_pm.stop_comfyui())
        return _json({"ok": False, "message": f"Unknown service: {svc}"}, 400)

    # ── GET /api/log-stream (SSE) ─────────────────────────────────────────────
    @app.route("/api/log-stream")
    def _log_stream():
        def _gen():
            q = _log_queue
            # Send last 50 lines from the log file first
            log_file = Path(_cfg.get("log_file", ""))
            if log_file.exists():
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for line in lines[-50:]:
                        yield f"data: {line}\n\n"
                except OSError:
                    pass
            # Then stream new lines
            while True:
                try:
                    line = q.get(timeout=10)
                    yield f"data: {line}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"  # keep-alive

        return Response(
            stream_with_context(_gen()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── POST /api/quit ────────────────────────────────────────────────────────
    @app.route("/api/quit", methods=["POST"])
    def _quit():
        import console as con
        threading.Timer(0.3, con.shutdown).start()
        return _json({"ok": True})

    # ── GET /api/config ───────────────────────────────────────────────────────
    @app.route("/api/config")
    def _config_get():
        return _json(_cfg)

    # ── POST /api/config ──────────────────────────────────────────────────────
    @app.route("/api/config", methods=["POST"])
    def _config_post():
        import config as cfg_module
        body = request.get_json(force=True) or {}
        _cfg.update(body)
        try:
            cfg_module.save(_cfg)
            return _json({"ok": True})
        except OSError as exc:
            return _json({"ok": False, "message": str(exc)}, 500)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _probe_duration(fp: Path) -> float:
    """Run ffprobe to get video duration. Returns 0.0 on failure."""
    ffprobe = _cfg.get("ffprobe_exe") or shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        import subprocess
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", str(fp)],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                return float(stream.get("duration", 0))
    except Exception:
        pass
    return 0.0


def _notify_cache_new(fp: Path) -> None:
    try:
        import library_cache as lc
        lc.probe_and_cache(fp)
    except Exception:
        pass


def _notify_cache_remove(fp: Path) -> None:
    try:
        import library_cache as lc
        lc.invalidate(fp.name)
    except Exception:
        pass


# ── Browser dashboard HTML ────────────────────────────────────────────────────
# Served at GET /dashboard. Self-contained: polls /api/status and /api/session/list
# every 3s, and tails /api/log-stream via EventSource.

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>EdgeVideo Console</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#06090E;color:#AABFD4;font-family:'Courier New',monospace;font-size:12px;padding:20px}
h1{color:#00C4AE;font-size:14px;letter-spacing:.1em;margin-bottom:18px;border-bottom:1px solid #1E2E40;padding-bottom:10px}
h2{color:#526878;font-size:9px;letter-spacing:.12em;text-transform:uppercase;margin:16px 0 8px}
.card{background:#0F1520;border:1px solid #1E2E40;border-radius:6px;padding:12px;margin-bottom:10px}
.row{display:flex;align-items:center;gap:10px;padding:4px 0;border-bottom:1px solid #0B1018}
.row:last-child{border-bottom:none}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.green{background:#22C85A}.amber{background:#E8A020}.red{background:#E85050}
.name{width:120px;color:#EBF4FF;font-weight:bold}
.port{width:60px;color:#526878}
.stat{width:80px}
.ok{color:#22C85A}.warn{color:#E8A020}.err{color:#E85050}.dim{color:#526878}
.btn{background:#003D38;color:#00C4AE;border:1px solid #00C4AE44;border-radius:4px;
     padding:4px 10px;cursor:pointer;font-family:inherit;font-size:10px;margin-left:auto}
.btn:hover{background:#00C4AE;color:#06090E}
.btn-red{background:#280A0A;color:#E85050;border-color:#E8505044}
.btn-red:hover{background:#E85050;color:#fff}
#log{background:#030810;border:1px solid #1E2E40;border-radius:4px;padding:10px;
     height:260px;overflow-y:auto;font-size:10px;line-height:1.7;white-space:pre-wrap;word-break:break-all}
.exports-idle{color:#526878;font-style:italic;padding:4px 0}
.disk-bar-bg{background:#1E2E40;border-radius:3px;height:6px;margin-top:6px}
.disk-bar{background:#00C4AE;border-radius:3px;height:6px;transition:width .5s}
.disk-warn .disk-bar{background:#E8A020}
.disk-crit .disk-bar .disk-bar{background:#E85050}
.refresh-stamp{color:#526878;font-size:9px;text-align:right;margin-top:4px}
.sessions{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.sess-card{background:#0B1018;border:1px solid #1E2E40;border-radius:5px;padding:8px;font-size:10px}
.sess-name{color:#EBF4FF;font-weight:bold;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sess-meta{color:#526878}
a{color:#4A94FF;text-decoration:none}a:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>&#9679; EdgeVideo Management Console</h1>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
  <!-- Left column -->
  <div>
    <h2>Services</h2>
    <div class="card" id="svc-panel">Loading…</div>

    <h2>Disk</h2>
    <div class="card" id="disk-panel">—</div>

    <h2>Active Exports</h2>
    <div class="card" id="exp-panel"><span class="exports-idle">idle</span></div>
  </div>

  <!-- Right column -->
  <div>
    <h2>Recent Sessions</h2>
    <div class="card" id="sess-panel">Loading…</div>
  </div>
</div>

<h2>Activity Log <span id="log-stamp" class="refresh-stamp"></span></h2>
<div id="log"></div>

<div style="margin-top:10px;display:flex;gap:8px;align-items:center">
  <button class="btn" onclick="window.open('/EdgeVideo_Gemma4.html','_blank')">Open App</button>
  <button class="btn" onclick="location.reload()">Refresh Page</button>
  <button class="btn btn-red" onclick="quitConsole()">Quit Console</button>
  <span class="dim" style="margin-left:auto;font-size:9px" id="stamp">—</span>
</div>

<script>
const $ = id => document.getElementById(id);

// ── Service status ─────────────────────────────────────────────────────────
async function refreshStatus() {
  try {
    const d = await fetch('/api/status').then(r => r.json());
    const svcs = [
      {key:'server',  label:'HTTP Server', port: d.server?.port,  ok: d.server?.ok},
      {key:'comfyui', label:'ComfyUI',     port: d.comfyui?.port, ok: d.comfyui?.ok,
       actions: `<button class="btn" onclick="restartComfy()">Restart</button>`},
      {key:'ollama',  label:'Ollama',      port: d.ollama?.port,  ok: d.ollama?.ok,
       note: '(auto)'},
      {key:'ffmpeg',  label:'ffmpeg',      port: null,
       ok: d.ffmpeg?.ok, note: d.ffmpeg?.ok ? 'detected' : 'NOT FOUND'},
    ];
    $('svc-panel').innerHTML = svcs.map(s => `
      <div class="row">
        <div class="dot ${s.ok ? 'green' : (s.key==='ollama'?'amber':'red')}"></div>
        <div class="name">${s.label}</div>
        <div class="port">${s.port ? ':'+s.port : ''}</div>
        <div class="stat ${s.ok ? 'ok' : (s.key==='ollama'?'warn':'err')}">
          ${s.ok ? 'RUNNING' : (s.note || 'OFFLINE')}
        </div>
        ${s.actions || ''}
      </div>`).join('');

    // Disk
    const disk = d.disk || {};
    const total = (disk.used_gb || 0) + (disk.free_gb || 0);
    const pct = total > 0 ? Math.round((disk.used_gb / total) * 100) : 0;
    const cls = disk.free_gb < 5 ? 'disk-crit' : disk.free_gb < 20 ? 'disk-warn' : '';
    $('disk-panel').innerHTML = `
      <div style="display:flex;justify-content:space-between">
        <span class="${disk.free_gb < 5 ? 'err' : disk.free_gb < 20 ? 'warn' : 'ok'}">
          ${disk.free_gb?.toFixed(1)} GB free
        </span>
        <span class="dim">${disk.used_gb?.toFixed(1)} GB used of ${total.toFixed(1)} GB</span>
      </div>
      <div class="disk-bar-bg ${cls}">
        <div class="disk-bar" style="width:${pct}%"></div>
      </div>`;

    $('stamp').textContent = 'Last updated: ' + new Date().toLocaleTimeString();
  } catch(e) {
    $('svc-panel').innerHTML = '<span class="err">Console offline</span>';
  }
}

// ── Exports ────────────────────────────────────────────────────────────────
async function refreshExports() {
  try {
    // We don't have a list-exports API, so check session list for any running jobs
    const d = await fetch('/api/session/list').then(r => r.json());
    const recent = (d.sessions || []).slice(0, 6);
    if (!recent.length) {
      $('exp-panel').innerHTML = '<span class="exports-idle">idle — no sessions yet</span>';
      $('sess-panel').innerHTML = '<span class="dim">No sessions yet</span>';
      return;
    }
    $('exp-panel').innerHTML = '<span class="exports-idle">idle</span>';
    $('sess-panel').innerHTML = '<div class="sessions">' + recent.map(s => `
      <div class="sess-card">
        <div class="sess-name" title="${s.id}">${s.projName || s.id}</div>
        <div class="sess-meta">${s.clipCount} clip(s) &nbsp;·&nbsp; ${s.hasOutput ? '&#10003; exported' : 'no output'}</div>
        <div class="sess-meta" style="margin-top:3px">${s.outputSize ? (s.outputSize/1e6).toFixed(1)+' MB' : ''}</div>
      </div>`).join('') + '</div>';
  } catch(e) {}
}

// ── Log stream via EventSource ─────────────────────────────────────────────
const logEl = $('log');
let evtSrc = null;
function connectLog() {
  if (evtSrc) evtSrc.close();
  evtSrc = new EventSource('/api/log-stream');
  evtSrc.onmessage = e => {
    if (e.data === ': ping') return;
    const line = document.createElement('div');
    const d = e.data;
    if (d.includes('ERROR')) line.style.color = '#E85050';
    else if (d.includes('WARN'))  line.style.color = '#E8A020';
    else if (d.includes('INFO'))  line.style.color = '#AABFD4';
    line.textContent = d;
    logEl.appendChild(line);
    // Keep last 200 lines
    while (logEl.children.length > 200) logEl.removeChild(logEl.firstChild);
    logEl.scrollTop = logEl.scrollHeight;
    $('log-stamp').textContent = new Date().toLocaleTimeString();
  };
  evtSrc.onerror = () => {
    setTimeout(connectLog, 5000);
  };
}

// ── Actions ────────────────────────────────────────────────────────────────
async function restartComfy() {
  const btn = event.target;
  btn.textContent = 'Restarting…'; btn.disabled = true;
  try {
    await fetch('/api/restart-comfyui', {method:'POST', body:''});
    setTimeout(() => { btn.textContent = 'Restart'; btn.disabled = false; refreshStatus(); }, 4000);
  } catch(e) { btn.textContent = 'Restart'; btn.disabled = false; }
}

async function quitConsole() {
  if (!confirm('Stop EdgeVideo Console?\\n\\nThe HTTP server and browser app will go offline.')) return;
  try { await fetch('/api/quit', {method:'POST', body:''}); } catch(e) {}
  document.body.innerHTML = '<div style="padding:40px;color:#E8A020;font-family:monospace">Console stopped. You can close this tab.</div>';
}

// ── Init ───────────────────────────────────────────────────────────────────
refreshStatus();
refreshExports();
connectLog();
setInterval(refreshStatus,  3000);
setInterval(refreshExports, 10000);
</script>
</body>
</html>
"""
