#Requires -Version 5.1
<#
.SYNOPSIS
    EdgeVideo — Windows 11 One-Shot Installation Script

.DESCRIPTION
    Installs all dependencies required to run the EdgeVideo application:
      - Python 3.12
      - Git
      - FFmpeg  (winget: Gyan.FFmpeg)
      - Ollama  (local AI server)
      - Gemma 4 E4B model  (~5 GB download)
      - Python packages from requirements.txt
      - Optional: ComfyUI + LTX-Video model weights

    Run this script from an elevated PowerShell prompt for best results.
    It is safe to run multiple times — already-installed components are skipped.

.NOTES
    Platform : Windows 11 (Windows 10 will work with a warning)
    Author   : EdgeVideo project
    Date     : 2026-05-17
#>

# ---------------------------------------------------------------------------
# GLOBAL HELPERS
# ---------------------------------------------------------------------------

function Write-Banner {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║        EdgeVideo — Windows 11 Installation Script        ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "  ──────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "  ──────────────────────────────────────────────────────────" -ForegroundColor Cyan
}

function Write-OK    { param([string]$Msg) Write-Host "  [OK]  $Msg" -ForegroundColor Green  }
function Write-Warn  { param([string]$Msg) Write-Host "  [!!]  $Msg" -ForegroundColor Yellow }
function Write-Err   { param([string]$Msg) Write-Host "  [ERR] $Msg" -ForegroundColor Red    }
function Write-Info  { param([string]$Msg) Write-Host "  [--]  $Msg" -ForegroundColor Gray   }

# Refresh the current session's PATH from the registry so newly installed
# tools (FFmpeg, Python, Git, Ollama) are visible without reopening the shell.
function Refresh-Path {
    $machinePath = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    $env:PATH    = "$machinePath;$userPath"
}

# Test whether a command exists anywhere on PATH.
function Test-Command {
    param([string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

# Run winget and return $true on success, $false on failure.
function Invoke-Winget {
    param([string[]]$Args)
    $proc = Start-Process -FilePath "winget" `
                          -ArgumentList ($Args -join " ") `
                          -NoNewWindow -Wait -PassThru
    return ($proc.ExitCode -eq 0)
}

# Track what was installed for the summary at the end.
$installed = [System.Collections.Generic.List[string]]::new()
$warnings  = [System.Collections.Generic.List[string]]::new()

# ---------------------------------------------------------------------------
# STEP 1 — BANNER
# ---------------------------------------------------------------------------
Write-Banner

# ---------------------------------------------------------------------------
# STEP 2 — WINDOWS 11 CHECK
# ---------------------------------------------------------------------------
Write-Section "Step 1 of 11 — Checking Operating System"

$osCaption = (Get-CimInstance Win32_OperatingSystem).Caption
$osBuild   = [System.Environment]::OSVersion.Version.Build

Write-Info "Detected OS: $osCaption (build $osBuild)"

if ($osBuild -ge 22000) {
    Write-OK "Windows 11 confirmed."
} else {
    Write-Warn "This script is designed for Windows 11 (build 22000+)."
    Write-Warn "Detected build $osBuild.  Installation will continue, but"
    Write-Warn "some features may behave differently on older Windows versions."
    $warnings.Add("OS is not Windows 11 (build $osBuild)")
}

# ---------------------------------------------------------------------------
# STEP 3 — WINGET CHECK
# ---------------------------------------------------------------------------
Write-Section "Step 2 of 11 — Checking winget (App Installer)"

if (-not (Test-Command "winget")) {
    Write-Err  "winget is not available on this system."
    Write-Warn "Please install 'App Installer' from the Microsoft Store:"
    Write-Warn "  https://apps.microsoft.com/detail/9NBLGGH4NNS1"
    Write-Err  "Installation cannot continue without winget.  Exiting."
    Pause
    exit 1
}

$wingetVer = & winget --version 2>&1
Write-OK "winget found: $wingetVer"

# ---------------------------------------------------------------------------
# STEP 4 — PYTHON 3.10+
# ---------------------------------------------------------------------------
Write-Section "Step 3 of 11 — Python 3.10+"

$pythonOk = $false
if (Test-Command "python") {
    $rawVer = & python --version 2>&1
    Write-Info "Found: $rawVer"
    # Parse major.minor
    if ($rawVer -match "Python (\d+)\.(\d+)") {
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 10)) {
            Write-OK "Python $maj.$min satisfies the >=3.10 requirement."
            $pythonOk = $true
        } else {
            Write-Warn "Python $maj.$min is older than 3.10 — will install 3.12."
        }
    }
}

if (-not $pythonOk) {
    Write-Info "Installing Python 3.12 via winget..."
    try {
        $ok = Invoke-Winget @("install", "--id", "Python.Python.3.12",
                               "--exact", "--silent",
                               "--accept-package-agreements",
                               "--accept-source-agreements")
        if ($ok) {
            Refresh-Path
            $ver = & python --version 2>&1
            Write-OK "Python installed: $ver"
            $installed.Add("Python 3.12")
        } else {
            throw "winget returned a non-zero exit code."
        }
    } catch {
        Write-Err "Failed to install Python: $_"
        Write-Warn "Download manually from https://www.python.org/downloads/"
        $warnings.Add("Python installation failed — install manually")
    }
}

# ---------------------------------------------------------------------------
# STEP 5 — GIT
# ---------------------------------------------------------------------------
Write-Section "Step 4 of 11 — Git"

if (Test-Command "git") {
    $gitVer = & git --version 2>&1
    Write-OK "Git already present: $gitVer"
} else {
    Write-Info "Installing Git via winget..."
    try {
        $ok = Invoke-Winget @("install", "--id", "Git.Git",
                               "--exact", "--silent",
                               "--accept-package-agreements",
                               "--accept-source-agreements")
        if ($ok) {
            Refresh-Path
            $gitVer = & git --version 2>&1
            Write-OK "Git installed: $gitVer"
            $installed.Add("Git")
        } else {
            throw "winget returned a non-zero exit code."
        }
    } catch {
        Write-Err "Failed to install Git: $_"
        Write-Warn "Download manually from https://git-scm.com/download/win"
        $warnings.Add("Git installation failed — install manually")
    }
}

# ---------------------------------------------------------------------------
# STEP 6 — FFMPEG
# ---------------------------------------------------------------------------
Write-Section "Step 5 of 11 — FFmpeg"

if (Test-Command "ffmpeg") {
    $ffVer = (& ffmpeg -version 2>&1 | Select-Object -First 1)
    Write-OK "FFmpeg already present: $ffVer"
} else {
    Write-Info "Installing FFmpeg (Gyan.FFmpeg) via winget..."
    try {
        $ok = Invoke-Winget @("install", "--id", "Gyan.FFmpeg",
                               "--exact", "--silent",
                               "--accept-package-agreements",
                               "--accept-source-agreements")
        if ($ok) {
            Refresh-Path
            # winget may install FFmpeg to a non-standard location; add common paths.
            $ffmpegPaths = @(
                "$env:ProgramFiles\FFmpeg\bin",
                "$env:ProgramFiles\Gyan\FFmpeg\bin",
                "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*\bin"
            )
            foreach ($p in $ffmpegPaths) {
                $resolved = Resolve-Path $p -ErrorAction SilentlyContinue
                if ($resolved -and (Test-Path "$resolved\ffmpeg.exe")) {
                    $env:PATH = "$($resolved.Path);$env:PATH"
                    [System.Environment]::SetEnvironmentVariable(
                        'PATH',
                        "$($resolved.Path);$([System.Environment]::GetEnvironmentVariable('PATH','Machine'))",
                        'Machine')
                    Write-Info "Added FFmpeg to PATH: $($resolved.Path)"
                    break
                }
            }
            Refresh-Path
            if (Test-Command "ffmpeg") {
                $ffVer = (& ffmpeg -version 2>&1 | Select-Object -First 1)
                Write-OK "FFmpeg installed: $ffVer"
                $installed.Add("FFmpeg (Gyan)")
            } else {
                Write-Warn "FFmpeg installed but not yet on PATH."
                Write-Warn "You may need to reopen your terminal or restart Windows."
                $warnings.Add("FFmpeg installed but PATH refresh may require a new terminal")
                $installed.Add("FFmpeg (Gyan) — restart terminal to activate")
            }
        } else {
            throw "winget returned a non-zero exit code."
        }
    } catch {
        Write-Err "Failed to install FFmpeg: $_"
        Write-Warn "Download manually from https://www.gyan.dev/ffmpeg/builds/"
        $warnings.Add("FFmpeg installation failed — install manually")
    }
}

# ---------------------------------------------------------------------------
# STEP 7 — OLLAMA
# ---------------------------------------------------------------------------
Write-Section "Step 6 of 11 — Ollama (local AI server)"

if (Test-Command "ollama") {
    $ollamaVer = & ollama --version 2>&1
    Write-OK "Ollama already present: $ollamaVer"
} else {
    Write-Info "Installing Ollama via winget..."
    try {
        $ok = Invoke-Winget @("install", "--id", "Ollama.Ollama",
                               "--exact", "--silent",
                               "--accept-package-agreements",
                               "--accept-source-agreements")
        if ($ok) {
            Refresh-Path
            Write-OK "Ollama installed."
            $installed.Add("Ollama")
        } else {
            throw "winget returned a non-zero exit code."
        }
    } catch {
        Write-Err "Failed to install Ollama: $_"
        Write-Warn "Download manually from https://ollama.com/download/windows"
        $warnings.Add("Ollama installation failed — install manually")
    }
}

# ---------------------------------------------------------------------------
# STEP 8 — PULL GEMMA 4 MODEL
# ---------------------------------------------------------------------------
Write-Section "Step 7 of 11 — Gemma 4 E4B model (via Ollama)"

Write-Warn "This step downloads the Gemma 4 E4B model (~5 GB)."
Write-Warn "Make sure you have sufficient disk space and a stable connection."
Write-Info "Starting ollama pull gemma4:e4b ..."

if (Test-Command "ollama") {
    try {
        # ollama serve must be running; start it in the background if needed.
        $ollamaProc = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
        if (-not $ollamaProc) {
            Write-Info "Starting Ollama service in the background..."
            Start-Process -FilePath "ollama" -ArgumentList "serve" `
                          -WindowStyle Hidden -PassThru | Out-Null
            Start-Sleep -Seconds 5   # Give the server a moment to bind.
        }

        Write-Info "Pulling gemma4:e4b — this may take several minutes..."
        # Run synchronously so the user can see progress.
        $pullResult = Start-Process -FilePath "ollama" `
                                    -ArgumentList "pull gemma4:e4b" `
                                    -NoNewWindow -Wait -PassThru
        if ($pullResult.ExitCode -eq 0) {
            Write-OK "gemma4:e4b model pulled successfully."
            $installed.Add("Ollama model: gemma4:e4b")
        } else {
            Write-Warn "ollama pull exited with code $($pullResult.ExitCode)."
            Write-Warn "The model may already be cached, or Ollama is not running."
            $warnings.Add("ollama pull gemma4:e4b returned exit code $($pullResult.ExitCode)")
        }
    } catch {
        Write-Err "Failed to pull Gemma 4 model: $_"
        Write-Warn "Run manually after install:  ollama pull gemma4:e4b"
        $warnings.Add("Gemma 4 model pull failed — run 'ollama pull gemma4:e4b' manually")
    }
} else {
    Write-Warn "ollama command not found — skipping model pull."
    Write-Warn "After installing Ollama, run:  ollama pull gemma4:e4b"
    $warnings.Add("Skipped model pull — ollama not on PATH")
}

# ---------------------------------------------------------------------------
# STEP 9 — NAVIGATE TO EDGEVIDEO DIRECTORY
# ---------------------------------------------------------------------------
Write-Section "Step 8 of 11 — EdgeVideo directory"

$edgeVideoDir = $PSScriptRoot
if (-not $edgeVideoDir) {
    # Fallback when dot-sourced or run interactively.
    $edgeVideoDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}

Write-Info "EdgeVideo root: $edgeVideoDir"

if (-not (Test-Path "$edgeVideoDir\requirements.txt")) {
    Write-Err "requirements.txt not found at $edgeVideoDir"
    Write-Err "Make sure you are running this script from the EdgeVideo repo root."
    Pause
    exit 1
}

Set-Location $edgeVideoDir
Write-OK "Working directory set to $edgeVideoDir"

# ---------------------------------------------------------------------------
# STEP 10 — PIP INSTALL -R REQUIREMENTS.TXT
# ---------------------------------------------------------------------------
Write-Section "Step 9 of 11 — Python packages (requirements.txt)"

try {
    Write-Info "Running: pip install -r requirements.txt"
    $pipResult = Start-Process -FilePath "python" `
                               -ArgumentList "-m pip install --upgrade -r requirements.txt" `
                               -NoNewWindow -Wait -PassThru
    if ($pipResult.ExitCode -eq 0) {
        Write-OK "All Python packages installed successfully."
        $installed.Add("Python packages (flask, watchdog, pystray, Pillow)")
    } else {
        throw "pip exited with code $($pipResult.ExitCode)"
    }
} catch {
    Write-Err "pip install failed: $_"
    Write-Warn "Try running manually: python -m pip install -r requirements.txt"
    $warnings.Add("pip install failed — run manually")
}

# ---------------------------------------------------------------------------
# STEP 11 — CREATE DATA DIRECTORIES
# ---------------------------------------------------------------------------
Write-Section "Step 10 of 11 — Data directories"

$dataDirs = @(
    "$env:USERPROFILE\EdgeVideo\gwf",
    "$env:USERPROFILE\EdgeVideo\sessions"
)

foreach ($dir in $dataDirs) {
    try {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-OK "Created: $dir"
            $installed.Add("Directory: $dir")
        } else {
            Write-Info "Already exists: $dir"
        }
    } catch {
        Write-Err "Could not create $dir — $($_)"
        $warnings.Add("Failed to create directory: $dir")
    }
}

# ---------------------------------------------------------------------------
# STEP 12 — OPTIONAL COMFYUI
# ---------------------------------------------------------------------------
Write-Section "Step 11 of 11 — Optional: ComfyUI + LTX-Video (AI transitions)"

Write-Host ""
Write-Host "  ComfyUI is an optional AI image/video generation backend used by" -ForegroundColor Yellow
Write-Host "  EdgeVideo for AI-powered transition generation (LTX-Video model)." -ForegroundColor Yellow
Write-Host "  This requires an NVIDIA GPU and downloads several GB of model weights." -ForegroundColor Yellow
Write-Host ""
$comfyChoice = Read-Host "  Install ComfyUI + LTX-Video model weights? [Y/N]"

if ($comfyChoice -match "^[Yy]") {

    $comfyDir = "C:\ComfyUI"

    # --- Clone ComfyUI ---
    try {
        if (Test-Path "$comfyDir\.git") {
            Write-Info "ComfyUI already cloned at $comfyDir — skipping clone."
        } elseif (Test-Path $comfyDir) {
            Write-Warn "$comfyDir exists but is not a git repo.  Skipping clone."
            Write-Warn "Remove the directory and re-run to get a fresh clone."
        } else {
            Write-Info "Cloning ComfyUI into $comfyDir ..."
            $cloneResult = Start-Process -FilePath "git" `
                                         -ArgumentList "clone https://github.com/comfyanonymous/ComfyUI.git $comfyDir" `
                                         -NoNewWindow -Wait -PassThru
            if ($cloneResult.ExitCode -ne 0) {
                throw "git clone exited with code $($cloneResult.ExitCode)"
            }
            Write-OK "ComfyUI cloned to $comfyDir"
            $installed.Add("ComfyUI (cloned to $comfyDir)")
        }
    } catch {
        Write-Err "Failed to clone ComfyUI: $_"
        $warnings.Add("ComfyUI clone failed — run: git clone https://github.com/comfyanonymous/ComfyUI.git C:\ComfyUI")
    }

    # --- Install ComfyUI Python requirements ---
    try {
        if (Test-Path "$comfyDir\requirements.txt") {
            Write-Info "Installing ComfyUI Python requirements..."
            $comfyPip = Start-Process -FilePath "python" `
                                      -ArgumentList "-m pip install -r $comfyDir\requirements.txt" `
                                      -NoNewWindow -Wait -PassThru
            if ($comfyPip.ExitCode -eq 0) {
                Write-OK "ComfyUI requirements installed."
                $installed.Add("ComfyUI Python requirements")
            } else {
                throw "pip exited with code $($comfyPip.ExitCode)"
            }
        } else {
            Write-Warn "ComfyUI requirements.txt not found — skipping pip install."
        }
    } catch {
        Write-Err "ComfyUI requirements install failed: $_"
        $warnings.Add("ComfyUI pip install failed — run manually in $comfyDir")
    }

    # --- Download LTX-Video model weights ---
    #
    # Official HuggingFace sources (Lightricks/LTX-Video repo):
    #   ltx-video-2b-v0.9.1.safetensors
    #     https://huggingface.co/Lightricks/LTX-Video/resolve/main/ltx-video-2b-v0.9.1.safetensors
    #   t5xxl_fp8_e4m3fn.safetensors  (text encoder)
    #     https://huggingface.co/mcmonkey/google_t5-v1_1-xxl_encoderonly/resolve/main/t5xxl_fp8_e4m3fn.safetensors
    #
    $modelDir = "$comfyDir\models\checkpoints"
    $clipDir  = "$comfyDir\models\clip"

    foreach ($d in @($modelDir, $clipDir)) {
        if (-not (Test-Path $d)) {
            New-Item -ItemType Directory -Path $d -Force | Out-Null
            Write-Info "Created model directory: $d"
        }
    }

    $modelFiles = @(
        @{
            Url  = "https://huggingface.co/Lightricks/LTX-Video/resolve/main/ltx-video-2b-v0.9.1.safetensors"
            Dest = "$modelDir\ltx-video-2b-v0.9.1.safetensors"
            Name = "LTX-Video 2B v0.9.1 (~6 GB)"
        },
        @{
            Url  = "https://huggingface.co/mcmonkey/google_t5-v1_1-xxl_encoderonly/resolve/main/t5xxl_fp8_e4m3fn.safetensors"
            Dest = "$clipDir\t5xxl_fp8_e4m3fn.safetensors"
            Name = "T5-XXL text encoder fp8 (~4.5 GB)"
        }
    )

    foreach ($model in $modelFiles) {
        if (Test-Path $model.Dest) {
            Write-Info "Already downloaded: $($model.Name)"
            continue
        }
        Write-Warn "Downloading $($model.Name) — this may take a long time..."
        Write-Info "  Source : $($model.Url)"
        Write-Info "  Dest   : $($model.Dest)"
        try {
            # Use BITS if available (shows progress, resumable); fall back to
            # Invoke-WebRequest for environments where BITS is unavailable.
            $bitsAvailable = Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue
            if ($bitsAvailable) {
                Start-BitsTransfer -Source $model.Url -Destination $model.Dest `
                                   -DisplayName "Downloading $($model.Name)" `
                                   -ErrorAction Stop
            } else {
                $ProgressPreference = 'SilentlyContinue'  # Speeds up Invoke-WebRequest.
                Invoke-WebRequest -Uri $model.Url -OutFile $model.Dest -UseBasicParsing
                $ProgressPreference = 'Continue'
            }
            Write-OK "Downloaded: $($model.Name)"
            $installed.Add("Model: $($model.Name)")
        } catch {
            Write-Err "Failed to download $($model.Name): $_"
            Write-Warn "Download manually:"
            Write-Warn "  $($model.Url)"
            Write-Warn "  -> $($model.Dest)"
            $warnings.Add("Model download failed: $($model.Name)")
        }
    }

    # --- Create _launch_comfy.bat ---
    $launchComfyPath = "$edgeVideoDir\_launch_comfy.bat"
    try {
        $launchComfyContent = @"
@echo off
title ComfyUI Server
echo Starting ComfyUI at http://127.0.0.1:8188
cd /d "C:\ComfyUI"
python main.py --listen 127.0.0.1 --port 8188
pause
"@
        Set-Content -Path $launchComfyPath -Value $launchComfyContent -Encoding UTF8
        Write-OK "Created launcher: $launchComfyPath"
        $installed.Add("_launch_comfy.bat")
    } catch {
        Write-Err "Could not create _launch_comfy.bat: $_"
        $warnings.Add("_launch_comfy.bat creation failed")
    }

} else {
    Write-Info "ComfyUI installation skipped."
}

# ---------------------------------------------------------------------------
# STEP 13 — DESKTOP SHORTCUT
# ---------------------------------------------------------------------------
Write-Section "Creating Desktop shortcut (EdgeVideo.lnk)"

try {
    $desktopPath  = [System.Environment]::GetFolderPath("Desktop")
    $shortcutPath = "$desktopPath\EdgeVideo.lnk"
    $targetBat    = "$edgeVideoDir\launch_EdgeVideo.bat"

    $wsh      = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath       = "cmd.exe"
    $shortcut.Arguments        = "/c `"$targetBat`""
    $shortcut.WorkingDirectory = $edgeVideoDir
    $shortcut.Description      = "Launch EdgeVideo local AI video editor"

    # Use the first .ico found in the project, or fall back to cmd.exe icon.
    $icoPath = Get-ChildItem -Path $edgeVideoDir -Filter "*.ico" -Recurse `
                             -ErrorAction SilentlyContinue |
               Select-Object -First 1 -ExpandProperty FullName
    if ($icoPath) {
        $shortcut.IconLocation = $icoPath
    } else {
        $shortcut.IconLocation = "%SystemRoot%\System32\cmd.exe,0"
    }

    $shortcut.Save()
    Write-OK "Desktop shortcut created: $shortcutPath"
    $installed.Add("Desktop shortcut: EdgeVideo.lnk")
} catch {
    Write-Err "Could not create desktop shortcut: $_"
    $warnings.Add("Desktop shortcut creation failed")
}

# ---------------------------------------------------------------------------
# STEP 14 — SMOKE TEST
# ---------------------------------------------------------------------------
Write-Section "Smoke test"

# Python imports
Write-Info "Testing Python imports: flask, pystray, PIL, watchdog..."
try {
    $pyTest = @"
import flask, pystray, PIL, watchdog
print('IMPORTS_OK')
"@
    $tempPy = [System.IO.Path]::GetTempFileName() + ".py"
    Set-Content -Path $tempPy -Value $pyTest -Encoding UTF8
    $pyOut = & python $tempPy 2>&1
    Remove-Item $tempPy -ErrorAction SilentlyContinue
    if ($pyOut -match "IMPORTS_OK") {
        Write-OK "Python imports: flask, pystray, PIL, watchdog — all OK."
    } else {
        Write-Warn "Python import test returned unexpected output:"
        Write-Warn "  $pyOut"
        $warnings.Add("Python import smoke test failed")
    }
} catch {
    Write-Err "Python import test failed: $_"
    $warnings.Add("Python import smoke test threw an exception")
}

# FFmpeg version
Write-Info "Testing ffmpeg -version..."
try {
    $ffOut = & ffmpeg -version 2>&1 | Select-Object -First 1
    if ($ffOut -match "ffmpeg version") {
        Write-OK "FFmpeg: $ffOut"
    } else {
        Write-Warn "ffmpeg returned unexpected output: $ffOut"
        $warnings.Add("ffmpeg -version smoke test unexpected output")
    }
} catch {
    Write-Warn "ffmpeg not found on PATH — smoke test skipped."
    $warnings.Add("ffmpeg not on PATH at smoke-test time")
}

# Ollama reachability
Write-Info "Checking Ollama at http://localhost:11434 ..."
try {
    $ollamaResp = Invoke-WebRequest -Uri "http://localhost:11434" `
                                    -UseBasicParsing `
                                    -TimeoutSec 5 `
                                    -ErrorAction Stop
    Write-OK "Ollama is reachable on localhost:11434 (HTTP $($ollamaResp.StatusCode))."
} catch {
    Write-Warn "Ollama is not reachable on localhost:11434."
    Write-Warn "Start it with:  ollama serve"
    $warnings.Add("Ollama not reachable at localhost:11434 — start with 'ollama serve'")
}

# ---------------------------------------------------------------------------
# STEP 15 — SUCCESS SUMMARY
# ---------------------------------------------------------------------------
Write-Section "Installation Summary"

if ($installed.Count -gt 0) {
    Write-Host "  Installed / configured:" -ForegroundColor Green
    foreach ($item in $installed) {
        Write-Host "    + $item" -ForegroundColor Green
    }
}

if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "  Warnings / action required:" -ForegroundColor Yellow
    foreach ($w in $warnings) {
        Write-Host "    ! $w" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────────────────┐" -ForegroundColor Cyan
Write-Host "  │  EdgeVideo is ready.  Launch it from the Desktop        │" -ForegroundColor Cyan
Write-Host "  │  shortcut or run:  launch_EdgeVideo.bat                 │" -ForegroundColor Cyan
Write-Host "  │                                                         │" -ForegroundColor Cyan
Write-Host "  │  Then open your browser at:  http://localhost:8765      │" -ForegroundColor Cyan
Write-Host "  └─────────────────────────────────────────────────────────┘" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Before starting, make sure Ollama is running:" -ForegroundColor Gray
Write-Host "    ollama serve" -ForegroundColor Gray
Write-Host ""

Pause
