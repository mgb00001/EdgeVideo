## Windows Shell Instructions

This machine blocks PowerShell -EncodedCommand due to security policy.

NEVER use PowerShell to run commands. Instead:
- Use `cmd /c` prefix for all shell commands
- To start a process: `cmd /c start "" "http://localhost:8765"`
- To run a Python script: `cmd /c python script.py`
- To start ComfyUI: `cmd /c start_comfyui.bat`
- Do not use Start-Process, -EncodedCommand, or any PowerShell cmdlets