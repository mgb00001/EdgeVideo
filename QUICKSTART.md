# EdgeVideo Quick Start Guide

EdgeVideo is a Windows 11 AI-assisted video editing application. A Python/Flask backend handles all processing server-side while you work through a browser-based UI. Gemma 4 analyses your clips, FFmpeg handles encoding, and ComfyUI (optional) generates AI video transitions.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Starting EdgeVideo](#2-starting-edgevideo)
3. [Importing Your First Clip](#3-importing-your-first-clip)
4. [Creating a Snippet](#4-creating-a-snippet)
5. [Building a Timeline](#5-building-a-timeline)
6. [Adding Transitions](#6-adding-transitions)
7. [Adding Audio](#7-adding-audio)
8. [Exporting Your Video](#8-exporting-your-video)
9. [The Dashboard](#9-the-dashboard)
10. [Stopping EdgeVideo](#10-stopping-edgevideo)
11. [Quick Reference Card](#11-quick-reference-card)

---

## 1. Prerequisites

Before launching EdgeVideo, confirm the following are in place.

### Required

| Requirement | How to verify |
|---|---|
| **Ollama** installed and running | Run `ollama list` in a terminal — you should see `gemma4:e4b` in the output |
| **Gemma 4 model pulled** | Run `ollama pull gemma4:e4b` if not already present |
| **FFmpeg** installed and on PATH | Run `ffmpeg -version` in a terminal — it should print version info |

### Optional (for AI Transitions)

| Requirement | Notes |
|---|---|
| **ComfyUI** installed | Runs on port 8188 |
| **LTX-Video model** | Must be loaded as a checkpoint in ComfyUI |
| **T5 encoder** | Filename configured in EdgeVideo Settings tab |

> **Note:** Ollama starts automatically and manages itself on port 11434. You do not need to start it manually before launching EdgeVideo — EdgeVideo will detect its status. However, the `gemma4:e4b` model must already be pulled, as EdgeVideo will not download it for you.

> **Note:** ComfyUI is entirely optional. All features except LTX-Video AI transitions work without it.

---

## 2. Starting EdgeVideo

### Launch

1. Open File Explorer and navigate to the EdgeVideo installation folder.
2. Double-click **`launch_EdgeVideo.bat`**.

### What happens next

- A console window opens showing the Flask server starting on **port 8765**.
- A system tray icon appears in the Windows notification area (bottom-right of the taskbar).
- Your default browser opens automatically to `http://localhost:8765/EdgeVideo_Gemma4.html`.

> **Tip:** If the browser does not open automatically, right-click the tray icon and choose **Open Browser**.

> **Tip:** If port 8765 is already in use by another application, change the port in the **Settings** tab after first launch, then restart EdgeVideo.

### System tray icon

Right-clicking the tray icon gives you the full control menu:

| Menu item | Action |
|---|---|
| Open Dashboard | Opens the live log/status dashboard in the browser |
| Open Browser | Opens the main editing UI |
| ComfyUI: RUNNING / STOPPED | Shows current ComfyUI status |
| Ollama: RUNNING / STOPPED | Shows current Ollama status |
| Restart ComfyUI | Kills and restarts the ComfyUI process |
| Open GWF Folder | Opens your Global Working Folder in Explorer |
| Open Sessions Folder | Opens the export sessions folder in Explorer |
| View Log File | Opens the application log file in your default text editor |
| Quit EdgeVideo | Shuts down the Flask server and removes the tray icon |

---

## 3. Importing Your First Clip

EdgeVideo reads video files from the **Global Working Folder (GWF)**. The default GWF path is:

```
%USERPROFILE%\EdgeVideo\gwf
```

Which expands to something like `C:\Users\YourName\EdgeVideo\gwf`.

### Steps

1. Open File Explorer and navigate to the GWF folder.
   - Shortcut: right-click the tray icon and choose **Open GWF Folder**.
2. Copy or move your video file(s) into the GWF folder. Any common format (MP4, MOV, MKV, AVI) is supported.
3. In the browser UI, click the **Library** tab.
4. Your clips appear as cards. If a clip has not been analysed yet, it shows a pending state.
5. Click the **Analyse** button on a clip card (or click the clip itself if analysis runs automatically). Gemma 4 will extract:
   - Subject description
   - Mood and tone
   - Pacing characteristics
   - Colour palette
6. Once analysis completes, the clip card displays the AI-generated metadata.
7. Click a clip card to **select it as the active clip**. The active clip is highlighted and becomes the source for the Snippets tab.

> **Note:** AI analysis requires Ollama and the `gemma4:e4b` model to be running. Analysis runs once per clip and is cached — re-opening the Library will not re-analyse already-processed clips.

> **Tip:** You can add clips to the GWF folder while EdgeVideo is running. Refresh the Library tab to see newly added files.

---

## 4. Creating a Snippet

A **snippet** is a trimmed segment of a clip, with an optional name and captions. Snippets are the building blocks of your timeline.

### Steps

1. In the **Library** tab, click a clip to make it the active clip.
2. Click the **Snippets** tab.
3. Use the video player controls to find the start of the section you want to keep.
4. Click **Set In Point** (or type a precise millisecond value in the In Point field) to mark the start.
5. Scrub forward to the end of the section you want.
6. Click **Set Out Point** (or type a millisecond value) to mark the end.
7. Enter a **name** for the snippet in the Name field (e.g., "Opening shot", "Interview closeup").
8. If you want captions on this snippet, enable the **Captions** toggle. Caption text can be entered or generated.
9. Click **Add to Timeline** to append the snippet to your sequence.

> **Tip:** In and Out Points use millisecond precision. If you know your exact timecodes, type them directly — for example, `3500` for 3.5 seconds in.

> **Tip:** You can create multiple snippets from the same source clip. Simply adjust the In/Out Points and add each one to the timeline separately.

> **Note:** Adding a snippet to the timeline does not remove it from the Snippets tab. You can add the same snippet multiple times if needed.

---

## 5. Building a Timeline

The **Timeline** tab is where you arrange snippets into a final sequence.

### Steps

1. Click the **Timeline** tab. All snippets you have added appear as a vertical list.
2. Each snippet card shows:
   - Snippet name
   - Duration (calculated from In/Out points)
   - Caption status (enabled or disabled)
3. **Reorder snippets** using one of two methods:
   - **Drag and drop** — grab a snippet card and drag it to a new position.
   - **Up/Down buttons** — use the arrow buttons on each card to move it one position at a time.
4. The **total timeline duration** is displayed at the bottom of the tab. This reflects the sum of all snippet durations, before transition overlap is calculated.

> **Tip:** Plan your sequence in the Timeline tab before moving to Effects. Transitions are defined per-pair of adjacent clips, so finalising order first saves rework.

> **Note:** Removing a snippet from the timeline does not delete it from the Snippets tab. You can re-add it at any time.

---

## 6. Adding Transitions

The **Effects** tab lets you set a transition for each pair of adjacent clips in the timeline.

### Transition types

| Transition | Description | Requirements |
|---|---|---|
| **Cut** | Instant switch from one clip to the next. No render time. | None |
| **Crossfade** | Smooth dissolve using FFmpeg's `xfade` filter. Fast to render. | FFmpeg (always available) |
| **LTX-Video AI** | Generates a new 2-second AI video clip that bridges the two shots. Slow but cinematic. | ComfyUI running with LTX-Video model loaded |

### Steps

1. Click the **Effects** tab.
2. The tab lists each adjacent pair in your timeline (e.g., "Snippet 1 → Snippet 2").
3. For each pair, click the transition type you want: **Cut**, **Crossfade**, or **LTX-Video AI**.
4. If you choose **LTX-Video AI**, EdgeVideo will call ComfyUI during export to generate the transition clip. This adds significant render time.

> **Note:** LTX-Video AI transitions require ComfyUI to be running with the correct checkpoint and T5 encoder. Check the tray icon status (ComfyUI: RUNNING) before export. If ComfyUI is stopped, right-click the tray icon and choose **Restart ComfyUI**.

> **Tip:** Use **Cut** for fast-paced or action content. Use **Crossfade** for smooth, documentary-style edits. Reserve **LTX-Video AI** for hero transitions where the AI-generated bridge adds genuine visual value — they are slow to render.

---

## 7. Adding Audio

The **Audio** tab allows you to add a music or narration track to your project.

### Steps

1. Click the **Audio** tab.
2. Click **Upload** and select an MP3, WAV, or AAC file from your computer.
3. The file is saved automatically to the current session folder.
4. Use the built-in **audio player** to preview the track. Verify the timing feels right against your expected video length (visible in the Timeline tab).

### Mix Crossfader

When you export, the **clip volume** and **audio mix crossfader** in the Export tab control how the uploaded track blends with the original audio from your video clips.

| Crossfader position | Result |
|---|---|
| All the way left | Clip audio only (original video sound, no music) |
| Centre (50/50) | Equal mix of clip audio and uploaded music track |
| All the way right | Music track only (original clip audio removed) |

> **Tip:** For a music video or montage, push the crossfader right to feature the music. For a documentary or interview piece, keep it left or at centre so dialogue remains audible.

> **Note:** The audio file is saved to the session folder at upload time. If you replace it with a new upload, the old file remains in the session folder but is no longer used.

---

## 8. Exporting Your Video

The **Export** tab runs the full render pipeline using FFmpeg on the server.

### Steps

1. Click the **Export** tab.
2. Enter a **project name**. This becomes the output filename.
3. Choose a **quality preset**:

   | Preset | Resolution | Use case |
   |---|---|---|
   | Draft | 720p | Fast preview, sharing drafts |
   | HD | 1080p | Standard delivery, social media |
   | 4K | 2160p | High-quality archival or professional delivery |

4. Set the **clip volume** slider to control how loud the original clip audio is in the final mix.
5. Position the **audio mix crossfader** (see Audio section above).
6. Click **Export**.

### During export

- A live **progress bar** appears showing the current encoding step.
- Status messages update in real time (e.g., "Generating AI transition 1 of 2...", "Encoding final video...").
- Do not close the browser tab during export — the UI displays progress from the Flask server. The server will continue even if you navigate away, but you will lose the progress display.

### After export

Three buttons appear when the render is complete:

| Button | Action |
|---|---|
| **Play** | Plays the exported video directly in the browser |
| **Save As** | Triggers a browser download so you can save the file to any location |
| **Delete** | Removes the export from the sessions folder |

> **Note:** Exported files are stored in the sessions folder (default: `%USERPROFILE%\EdgeVideo\sessions`). Even after closing the Export tab, your files remain there and are accessible from the **Archive** tab.

> **Tip:** Export to Draft first to check timing and transitions, then re-export at HD or 4K for final delivery.

---

## 9. The Dashboard

The dashboard is a separate browser page for monitoring EdgeVideo's status. Open it at:

```
http://localhost:8765/dashboard
```

Or via the tray icon: right-click → **Open Dashboard**.

### What the dashboard shows

- **Live log stream** — a real-time feed of server-side events, including FFmpeg output, AI model calls, file operations, and errors.
- **Service status indicators** — at-a-glance status for:
  - Flask server (always running if the dashboard is accessible)
  - Ollama (port 11434)
  - ComfyUI (port 8188)

> **Tip:** Keep the dashboard open in a second browser tab while you work in the main UI. If something goes wrong during export or AI analysis, the live log is the fastest way to see what happened.

> **Note:** The dashboard is read-only. All controls are in the main UI or the tray icon menu.

---

## 10. Stopping EdgeVideo

1. Right-click the **system tray icon** in the Windows notification area.
2. Choose **Quit EdgeVideo**.

This shuts down the Flask server cleanly and removes the tray icon. Any in-progress export will be interrupted.

> **Note:** Closing the browser window does not stop EdgeVideo. The Flask server and tray icon continue running in the background until you choose Quit EdgeVideo from the tray menu.

> **Tip:** If the tray icon disappears but the server is still running (check Task Manager for `python.exe` or `console.py`), you can stop it by closing the console window that opened at launch, or by ending the Python process in Task Manager.

---

## 11. Quick Reference Card

### Application URLs

| URL | Purpose |
|---|---|
| `http://localhost:8765/EdgeVideo_Gemma4.html` | Main editing UI |
| `http://localhost:8765/dashboard` | Live log and service status |

### Default Folder Paths

| Folder | Default path |
|---|---|
| Global Working Folder (GWF) | `%USERPROFILE%\EdgeVideo\gwf` |
| Sessions (exports) | `%USERPROFILE%\EdgeVideo\sessions` |

### Service Ports

| Service | Port |
|---|---|
| EdgeVideo Flask server | 8765 |
| Ollama (Gemma 4) | 11434 |
| ComfyUI (AI transitions) | 8188 |

### Tab Summary

| Tab | What you do there |
|---|---|
| Library | Import clips from GWF, run AI analysis, select active clip |
| Snippets | Set In/Out points, name the snippet, add to timeline |
| Timeline | Arrange snippet order, drag/reorder, view total duration |
| Effects | Set Cut / Crossfade / LTX-Video AI per clip pair |
| Audio | Upload MP3/WAV/AAC, preview with player |
| Export | Choose quality, set mix, click Export, play/save result |
| Archive | Browse all past exports, play/download/delete |
| Settings | Configure paths, port, API keys, ComfyUI model filenames |

### Tray Icon Menu Summary

| Menu item | Action |
|---|---|
| Open Dashboard | `http://localhost:8765/dashboard` |
| Open Browser | `http://localhost:8765/EdgeVideo_Gemma4.html` |
| Restart ComfyUI | Restart the ComfyUI process |
| Open GWF Folder | Opens `%USERPROFILE%\EdgeVideo\gwf` in Explorer |
| Open Sessions Folder | Opens `%USERPROFILE%\EdgeVideo\sessions` in Explorer |
| View Log File | Opens log in default text editor |
| Quit EdgeVideo | Stops server, removes tray icon |

### Transition Types at a Glance

| Type | Speed | Requirement | Best for |
|---|---|---|---|
| Cut | Instant | None | Action, fast cuts |
| Crossfade | Fast (FFmpeg) | FFmpeg | Smooth narrative edits |
| LTX-Video AI | Slow (AI render) | ComfyUI + LTX-Video model | Hero/cinematic transitions |

### Audio Mix Crossfader

```
[Clip audio only] ------- [50/50 mix] ------- [Music only]
      LEFT                   CENTRE                RIGHT
```

### Export Quality Presets

| Preset | Resolution | Best for |
|---|---|---|
| Draft | 720p | Quick preview |
| HD | 1080p | Social media, standard delivery |
| 4K | 2160p | Professional / archival |

---

*EdgeVideo — AI-assisted video editing for Windows 11*
