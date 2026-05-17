"""
process_manager.py — EdgeVideo Console process lifecycle manager.

Responsibilities:
  - Start / stop / restart ComfyUI (the only fully-managed service)
  - Monitor ComfyUI and Ollama ports (health check loop, every 5s)
  - Start ffmpeg export jobs (cmd /c powershell export.ps1)
  - Track ExportJob state, persist to console_state.json
  - Recover in-progress jobs after console restart

All long-running work runs in daemon threads so this module
never blocks the Flask request handler or Tkinter main thread.
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("edgevideo.pm")

# Windows process creation flag — no console window
CREATE_NO_WINDOW = 0x08000000

# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ExportJob:
    sid: str
    pid: int
    status: str          # queued | running | done | error
    proj_name: str
    swf_path: str
    log_path: str
    err_path: str
    output_path: str
    output_size: int = 0
    frame: int = 0
    elapsed: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error_msg: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ExportJob":
        return ExportJob(**{k: v for k, v in d.items() if k in ExportJob.__dataclass_fields__})


# ── ProcessManager ─────────────────────────────────────────────────────────────

class ProcessManager:
    """
    Manages ComfyUI lifetime and all export subprocess jobs.
    Thread-safe: all public methods acquire self._lock before touching state.
    """

    def __init__(self, cfg: dict, on_status_change: Optional[Callable] = None):
        self._cfg = cfg
        self._on_status_change = on_status_change  # called by health loop on change
        self._lock = threading.Lock()

        # Current status snapshot (updated by health loop)
        self.status: dict = {
            "comfyui": {"ok": False, "pid": None},
            "ollama":  {"ok": False},
            "ffmpeg":  {"ok": False, "path": ""},
        }

        # Active export jobs: sid → ExportJob
        self._jobs: dict[str, ExportJob] = {}

        # ComfyUI Popen handle (for the process we launched, if any)
        self._comfy_proc: Optional[subprocess.Popen] = None

        # State file
        self._state_path = Path(cfg.get("sessions_path", "")).parent / "console_state.json"

        # Health check thread
        self._health_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── Startup / shutdown ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Load persisted state and start the health check loop."""
        self._load_state()
        self._check_ffmpeg()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="health-check"
        )
        self._health_thread.start()
        log.info("ProcessManager started.")

    def stop(self) -> None:
        """Signal the health loop to exit."""
        self._stop_event.set()
        log.info("ProcessManager stopped.")

    # ── Port health checks ─────────────────────────────────────────────────────

    @staticmethod
    def check_port(port: int, host: str = "127.0.0.1") -> bool:
        """Return True if something is listening on host:port."""
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            return False

    def _health_loop(self) -> None:
        while not self._stop_event.wait(5.0):
            changed = False
            with self._lock:
                # ComfyUI
                comfy_ok = self.check_port(self._cfg.get("comfyui_port", 8188))
                if comfy_ok != self.status["comfyui"]["ok"]:
                    self.status["comfyui"]["ok"] = comfy_ok
                    changed = True
                    log.info("ComfyUI port %s: %s",
                             self._cfg.get("comfyui_port", 8188),
                             "UP" if comfy_ok else "DOWN")

                # Ollama (monitor only)
                ollama_ok = self.check_port(self._cfg.get("ollama_port", 11434))
                if ollama_ok != self.status["ollama"]["ok"]:
                    self.status["ollama"]["ok"] = ollama_ok
                    changed = True

                # Poll running export jobs
                for job in list(self._jobs.values()):
                    if job.status == "running":
                        self._poll_job(job)
                        changed = True

            if changed and self._on_status_change:
                try:
                    self._on_status_change(self.get_status_snapshot())
                except Exception:
                    pass

    def get_status_snapshot(self) -> dict:
        """Return a serialisable copy of the current status dict."""
        with self._lock:
            ffmpeg_path = self._cfg.get("ffmpeg_exe", "")
            disk_path = str(Path(self._cfg.get("gwf_path", "")).parent)
            try:
                usage = shutil.disk_usage(disk_path)
                used_gb = round(usage.used / 1e9, 1)
                free_gb = round(usage.free / 1e9, 1)
            except OSError:
                used_gb = free_gb = 0.0

            return {
                "comfyui": dict(self.status["comfyui"]),
                "ollama":  dict(self.status["ollama"]),
                "ffmpeg":  dict(self.status["ffmpeg"]),
                "disk": {
                    "path": disk_path,
                    "used_gb": used_gb,
                    "free_gb": free_gb,
                },
            }

    def _check_ffmpeg(self) -> None:
        path = self._cfg.get("ffmpeg_exe", "")
        ok = bool(path) and Path(path).exists()
        self.status["ffmpeg"] = {"ok": ok, "path": path}
        if not ok:
            log.warning("ffmpeg not found at: %s", path)

    # ── ComfyUI management ─────────────────────────────────────────────────────

    def start_comfyui(self) -> dict:
        """Start ComfyUI if not already running. Returns {ok, message}."""
        port = self._cfg.get("comfyui_port", 8188)
        if self.check_port(port):
            return {"ok": True, "message": "ComfyUI already running."}

        bat_path = self._write_comfy_bat()
        if not bat_path:
            return {"ok": False, "message": "ComfyUI not configured (check comfyui_python in config)."}

        log.info("Starting ComfyUI via %s", bat_path)
        try:
            proc = subprocess.Popen(
                ["cmd.exe", "/c", str(bat_path)],
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._comfy_proc = proc
            log.info("ComfyUI launched, PID %s", proc.pid)
            return {"ok": True, "message": f"ComfyUI starting (PID {proc.pid})."}
        except OSError as exc:
            log.error("Failed to start ComfyUI: %s", exc)
            return {"ok": False, "message": str(exc)}

    def stop_comfyui(self) -> dict:
        """Kill all python.exe processes that look like ComfyUI main.py."""
        killed = 0
        try:
            # Use tasklist + wmic to find PIDs (no psutil dependency)
            result = subprocess.run(
                ["wmic", "process", "where",
                 "name='python.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
                capture_output=True, text=True, timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            for line in result.stdout.splitlines():
                if "main.py" in line and "ComfyUI" in line:
                    parts = line.split(",")
                    if len(parts) >= 3:
                        try:
                            pid = int(parts[-1].strip())
                            subprocess.run(
                                ["taskkill", "/F", "/PID", str(pid)],
                                capture_output=True, creationflags=CREATE_NO_WINDOW,
                            )
                            log.info("Killed ComfyUI PID %s", pid)
                            killed += 1
                        except (ValueError, OSError):
                            pass
        except Exception as exc:
            log.error("stop_comfyui error: %s", exc)
            return {"ok": False, "message": str(exc)}

        with self._lock:
            self._comfy_proc = None
        return {"ok": True, "message": f"Killed {killed} ComfyUI process(es)."}

    def restart_comfyui(self) -> dict:
        """Stop then start ComfyUI. Returns {ok, message}."""
        log.info("Restarting ComfyUI...")
        stop_result = self.stop_comfyui()
        if stop_result.get("ok") and "Killed" in stop_result.get("message", ""):
            time.sleep(1.5)
        return self.start_comfyui()

    def _write_comfy_bat(self) -> Optional[Path]:
        """Write _launch_comfy.bat to the EdgeVideo data dir. Returns path or None."""
        py = self._cfg.get("comfyui_python", "")
        main_dir = self._cfg.get("comfyui_main_dir", "")
        if not py or not Path(py).exists():
            log.warning("ComfyUI python not found: %s", py)
            return None

        bat_path = Path(self._cfg.get("gwf_path", "")).parent / "_launch_comfy.bat"
        lines = ["@echo off"]
        for k, v in self._cfg.get("comfyui_env", {}).items():
            lines.append(f'set "{k}={v}"')
        lines.append(f'cd /d "{main_dir}"')
        args = " ".join(f'"{a}"' for a in self._cfg.get("comfyui_args", ["main.py"]))
        lines.append(f'"{py}" {args}')

        bat_path.write_text("\r\n".join(lines), encoding="ascii")
        log.info("Wrote ComfyUI launcher: %s", bat_path)
        return bat_path

    # ── Export jobs ────────────────────────────────────────────────────────────

    def start_export(self, sid: str, script_content: str, proj_name: str, swf_path: str) -> ExportJob:
        """
        Write export.ps1 to swf_path and spawn it via cmd /c powershell.
        Returns an ExportJob (already added to self._jobs).
        """
        swf = Path(swf_path)
        script_path = swf / "export.ps1"
        log_path    = swf / "export.log"
        err_path    = swf / "export_err.log"
        output_path = swf / f"{proj_name}.mp4"

        # Clean previous run artefacts
        for f in (output_path, log_path, err_path):
            if f.exists():
                f.unlink(missing_ok=True)

        # Write script (UTF-8 no-BOM — PowerShell 5.1 reads it cleanly)
        script_path.write_text(script_content, encoding="utf-8-sig")

        # Copy Arial Bold font for drawtext filter
        font_src = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts" / "arialbd.ttf"
        if font_src.exists():
            shutil.copy2(font_src, swf / "arialbd.ttf")

        # Redirect stdout/stderr inside cmd so log files are populated
        cmd = (
            f'cmd.exe /c powershell -NoProfile -ExecutionPolicy Bypass '
            f'-File "{script_path}" > "{log_path}" 2> "{err_path}"'
        )
        proc = subprocess.Popen(
            cmd,
            shell=False,
            cwd=str(swf),
            creationflags=CREATE_NO_WINDOW,
        )

        job = ExportJob(
            sid=sid,
            pid=proc.pid,
            status="running",
            proj_name=proj_name,
            swf_path=str(swf),
            log_path=str(log_path),
            err_path=str(err_path),
            output_path=str(output_path),
        )
        # Store Popen so we can check exit code
        job._proc = proc  # type: ignore[attr-defined]

        with self._lock:
            self._jobs[sid] = job
        self._persist_state()
        log.info("[Export %s] PID %s started — %s.mp4", sid, proc.pid, proj_name)
        return job

    def get_export_status(self, sid: str) -> Optional[dict]:
        """Return a dict suitable for the export-status API, or None if unknown."""
        with self._lock:
            job = self._jobs.get(sid)
            if job is None:
                return None
            if job.status == "running":
                self._poll_job(job)
            return self._job_to_api(job)

    def _poll_job(self, job: ExportJob) -> None:
        """Update job status in-place. Must be called under self._lock."""
        proc = getattr(job, "_proc", None)
        job.elapsed = int(time.time() - job.start_time)

        # Parse latest frame from ffmpeg stderr
        err_path = Path(job.err_path)
        if err_path.exists():
            try:
                lines = err_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in reversed(lines[-20:]):
                    if "frame=" in line:
                        import re
                        m = re.search(r"frame=\s*(\d+)", line)
                        if m:
                            job.frame = int(m.group(1))
                        break
            except OSError:
                pass

        # Check if process has exited
        if proc is not None:
            ret = proc.poll()
            if ret is not None and job.status == "running":
                out = Path(job.output_path)
                if ret == 0 and out.exists() and out.stat().st_size > 0:
                    job.status = "done"
                    job.output_size = out.stat().st_size
                    job.end_time = time.time()
                    log.info("[Export %s] Done — %s MB", job.sid,
                             round(job.output_size / 1e6, 1))
                    # Generate thumbnail in background
                    threading.Thread(
                        target=self._gen_thumbnail, args=(job,), daemon=True
                    ).start()
                else:
                    job.status = "error"
                    job.end_time = time.time()
                    # Grab first error line for the message
                    err_path = Path(job.err_path)
                    if err_path.exists():
                        for line in err_path.read_text(errors="ignore").splitlines():
                            if line.strip():
                                job.error_msg = line.strip()[:200]
                                break
                    log.error("[Export %s] Failed (exit %s): %s", job.sid, ret, job.error_msg)
                self._persist_state()

    def _gen_thumbnail(self, job: ExportJob) -> None:
        ffmpeg = self._cfg.get("ffmpeg_exe") or shutil.which("ffmpeg") or "ffmpeg"
        thumb = Path(job.swf_path) / "thumbnail.jpg"
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", job.output_path,
                 "-ss", "00:00:02", "-vframes", "1", "-q:v", "2", str(thumb)],
                capture_output=True, timeout=30,
                creationflags=CREATE_NO_WINDOW,
            )
            log.info("[Export %s] Thumbnail generated.", job.sid)
        except Exception as exc:
            log.warning("[Export %s] Thumbnail failed: %s", job.sid, exc)

    def _job_to_api(self, job: ExportJob) -> dict:
        d: dict = {
            "status": job.status,
            "frame": job.frame,
            "elapsed": job.elapsed,
        }
        if job.status == "done":
            d["outputFile"] = f"{job.proj_name}.mp4"
            d["outputSize"] = job.output_size
        if job.status == "error":
            d["error"] = job.error_msg
        return d

    def remove_job(self, sid: str) -> None:
        with self._lock:
            self._jobs.pop(sid, None)
        self._persist_state()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _persist_state(self) -> None:
        try:
            data = {sid: job.to_dict() for sid, job in self._jobs.items()}
            self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not persist state: %s", exc)

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            for sid, d in data.items():
                try:
                    job = ExportJob.from_dict(d)
                    # If it was marked running, check if PID is still alive
                    if job.status == "running":
                        if self._pid_alive(job.pid):
                            log.info("[Export %s] Re-attached to PID %s", sid, job.pid)
                            job._proc = None  # type: ignore[attr-defined]
                        else:
                            job.status = "error"
                            job.error_msg = "Console restarted while job was running."
                            log.warning("[Export %s] Was running, PID %s gone — marked error",
                                        sid, job.pid)
                    self._jobs[sid] = job
                except Exception as exc:
                    log.warning("Could not restore job %s: %s", sid, exc)
        except Exception as exc:
            log.warning("Could not load console_state.json: %s", exc)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
