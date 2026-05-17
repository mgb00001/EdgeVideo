# EdgeVideo — AI-Powered Video Compilation Studio

> **A local-first, AI-assisted video editing and compilation suite for Windows 11.**  
> Powered by Gemma 4 · LTX-Video · FFmpeg · Python · Flask

![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-Apache%202.0-22C85A?style=for-the-badge)
![AI](https://img.shields.io/badge/AI-Local%20%26%20Private-E8A020?style=for-the-badge)

---

## What is EdgeVideo?

EdgeVideo is a browser-based video editing and compilation studio that runs entirely on your own Windows 11 machine. It combines a Python backend (Flask server + system tray), a full-featured browser UI, and two optional AI engines:

- **Gemma 4 via Ollama** — multimodal clip analysis, scene descriptions, AI assistance
- **LTX-Video via ComfyUI** — AI-generated transition clips between scenes

All video encoding is handled by **FFmpeg**, running server-side. No cloud rendering, no subscriptions, no data leaving your machine.

---

## Quick Start

```bat
REM 1. Install dependencies (one-time)
INSTALL_WINDOWS.ps1

REM 2. Start the console
launch_EdgeVideo.bat
```

The browser opens automatically at `http://localhost:8765/EdgeVideo_Gemma4.html`.

See **[QUICKSTART.md](QUICKSTART.md)** for a full walkthrough.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│           Browser UI  (EdgeVideo_Gemma4.html)        │
│      React 18 · Babel · Lucide · http://localhost    │
└────────────────────┬─────────────────────────────────┘
                     │  HTTP / REST  (port 8765)
┌────────────────────▼─────────────────────────────────┐
│           Python Console  (console.py)               │
│  Flask server · ProcessManager · Library cache       │
│  Tkinter hidden root · pystray tray icon             │
└────┬──────────────┬───────────────┬──────────────────┘
     │              │               │
 FFmpeg         Ollama          ComfyUI
(encoding)    port 11434       port 8188
             Gemma 4 E4B     LTX-Video 2B
```

---

## File Structure

```
EdgeVideo/
├── console.py            # Main entry point — Flask + tray + Tkinter mainloop
├── server.py             # Flask HTTP server (31 routes)
├── process_manager.py    # ComfyUI lifecycle + export job management
├── library_cache.py      # Background ffprobe cache + watchdog
├── config.py             # Auto-detecting config (ffmpeg, paths)
├── tray.py               # pystray system tray icon
├── EdgeVideo_Gemma4.html # Complete browser UI (React, single file)
├── launch_EdgeVideo.bat  # One-click launcher
├── install.bat           # pip install -r requirements.txt
├── INSTALL_WINDOWS.ps1   # Full one-shot Windows 11 setup script
├── QUICKSTART.md         # Step-by-step user guide
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

---

## Use Cases

### Use Case 1 — Taking a Snippet from a Single Video

You have one long video (a concert performance, a sports event, a family recording) and want to extract a specific moment from it.

**How:** Copy the video into your GWF folder (`%USERPROFILE%\EdgeVideo\gwf`). Open the **Library** tab — the clip appears automatically. Click it to make it active, then switch to **Snippets**. Use the video scrubber to find your moment, click **Set In** at the start and **Set Out** at the end. Name the snippet and click **Add to Timeline**. Go to **Export**, set your quality, and click **Export**. The result is an MP4 containing only your chosen segment.

---

### Use Case 2 — Taking Multiple Snippets from a Single Video

You want several separate moments from one long video — for example, three different songs from a full concert recording.

**How:** With the concert video in the Library, go to **Snippets** and trim the first song (set In/Out, name it "Song 1", Add to Timeline). Without changing clips, move the scrubber to the second song, set new In/Out points, name it "Song 2", Add to Timeline again. Repeat for the third. Each snippet is a separate timeline entry from the same source file. Export produces a compilation of all three in sequence.

---

### Use Case 3 — Creating a Compilation from Multiple Snippets of One Video

You want a highlights reel from a single long source — the best moments of a performance, a wedding speech with audience reactions, or a training session montage.

**How:** Follow Use Case 2 to create multiple snippets. Then open the **Timeline** tab to review the running order. Reorder snippets by dragging or using the up/down buttons. Check the total duration shown at the top. When the order is right, export at the desired quality. The result is a single polished compilation file that can be shared or posted directly.

---

### Use Case 4 — Taking Snippets from Multiple Videos

You have footage from several different sources — multiple cameras at the same event, clips from different days, or footage of different performers — and want to pull specific moments from each.

**How:** Place all source videos in your GWF folder. The **Library** tab lists them all with AI-generated metadata (subject, mood, pacing, colour palette) if Ollama is running. Click each video in turn to make it active, switch to **Snippets**, trim your chosen moment, name it, and add it to the Timeline. Repeat for each source video. The timeline accumulates entries from multiple sources, each referencing its own GWF file.

---

### Use Case 5 — Building a Multi-Clip Compilation from Multiple Videos

The classic "highlights video" scenario: pick the best moments from many different clips and assemble them into one coherent compilation.

**How:** Work through each source video as in Use Case 4, adding all your chosen snippets to the timeline. Open the **Timeline** tab to arrange them in narrative order — group by theme, chronology, or energy level. Check the total running time. Move to **Export**, choose HD or 4K depending on your use, set the project name, and export. FFmpeg concatenates all clips server-side with proper resolution normalisation (all clips are scaled to 1920×1080 at 24fps).

---

### Use Case 6 — Adding Transition Clips Between Scenes

Hard cuts between clips can feel abrupt. EdgeVideo supports three transition styles: instant cut, crossfade, or a fully AI-generated 2-second transition video.

**How:** After building your timeline, open the **Effects** tab. Between each pair of clips you will see a transition control. Select **Crossfade** for a smooth dissolve (FFmpeg `xfade` filter). For an AI transition, select **LTX-Video** — EdgeVideo generates a prompt based on the two adjacent clips, sends it to ComfyUI, and renders a 2-second video that visually bridges the two scenes. The generated clip is saved to the session folder and embedded in the export. You can also upload your own pre-made transition video clip.

> **Note:** AI transitions require ComfyUI running on port 8188 with the LTX-Video 2B checkpoint and T5-XXL encoder loaded.

---

### Use Case 7 — Generating AI Transition Clips with Custom Prompts

You want a specific AI-generated visual moment between two scenes — not just an automatic interpolation, but a deliberate creative choice.

**How:** In the **Effects** tab, click the transition between two clips. Select **LTX-Video**. You can edit the auto-generated prompt before sending — for example, change "slow dissolve to indoor venue" to "burst of light rays revealing a crowd". Adjust frame count (25 to 97 frames at 24fps = ~1 to 4 seconds). Click **Generate**. ComfyUI renders the clip and it appears as a thumbnail in the transition slot. Re-generate as many times as you like — each render uses a new random seed.

---

### Use Case 8 — Adding and Mixing an Audio Track with Video

You want to overlay a music track or voiceover on top of your compilation, with control over the balance between the original video sound and the new audio.

**How:** Open the **Audio** tab. Drag and drop an MP3, WAV, AAC, or FLAC file onto the drop zone, or click to browse. The file is saved to the session folder and an inline player lets you preview it. In the **Export** tab, the **AUDIO MIX** crossfader controls the balance: drag the thumb left for more clip audio, right for more music, or centre for a 50/50 blend. Both tracks can be at full volume simultaneously at the midpoint. The mix values are applied as FFmpeg `volume` filters and blended with `amix`.

---

### Use Case 9 — Adding Captions to Snippets

You want to add text overlays to specific clips — song titles, location names, speaker introductions, subtitles.

**How:** In the **Snippets** tab, after setting your In/Out points, scroll to the **Caption** section. Enable the caption toggle, type your text, and set the font size, start time (seconds from the beginning of the clip), and duration. The caption is rendered as a white text box with a semi-transparent black background using FFmpeg's `drawtext` filter. Different snippets can have different captions, and each caption's timing is automatically offset to its correct absolute position in the final compilation.

---

### Use Case 10 — Playing, Saving, and Deleting Compilations

After exporting, you want to review, keep, or clean up your compilations.

**How:** When export completes, the **Export** panel shows three actions: **Play** (streams the MP4 directly in the browser using the built-in video player), **Save As** (downloads the file through the browser's native Save dialog — choose any location on your machine), and **Delete** (removes the session folder). The **Archive** tab lists every past export session with thumbnail, duration, clip count, and file size. From there you can Play, Save As, or Delete any previous compilation. Sessions are stored in `%USERPROFILE%\EdgeVideo\sessions\`.

---

### Use Case 11 — AI Clip Analysis and Metadata Tagging

You have a large library of clips and want to quickly understand what is in each one without watching them all.

**How:** Place all clips in the GWF folder and open the **Library** tab. With Ollama and Gemma 4 running, click **Analyse** on any clip. Gemma 4 receives three sample frames from the video (distributed across the duration) and returns a structured analysis: subject, action, setting, mood, dominant colour palette (as hex values), a suggested clip label, editing notes, and a pacing rating (slow / medium / fast). This metadata is cached locally so subsequent library loads are instant. Use the analysis results to make informed decisions about which clips to include and how to order them.

---

### Use Case 12 — Concert or Live Event Highlights Reel

You recorded a full live concert or sporting event and want a 3–5 minute highlights package to share on YouTube or social media.

**How:** Copy the full-length recording(s) to the GWF folder. Use the **Snippets** tab to mark the best moments — the opening number, a crowd reaction, a spectacular goal, the finale. Use the **Audio** tab to layer a short music bed underneath, mixed low so the live audio dominates. In **Effects**, add crossfade transitions between songs/plays to smooth the flow. Export at HD quality. The result is a shareable highlights package that plays as a coherent narrative rather than a raw dump of footage.

---

### Use Case 13 — Creating a Narrative Short Film from Raw Footage

You shot a short film or documentary and have raw clips that need assembling into a coherent story.

**How:** Organise clips in the GWF folder by scene. Use **Library** AI analysis to understand the visual character of each clip. Build the story in the **Timeline** — each snippet is a scene. Use AI-generated transitions in **Effects** to bridge scene changes with atmospheric in-between frames. Add captions in **Snippets** for title cards, location text, and dialogue subtitles. Mix location audio with a score in **Audio**. Export at 4K if your source footage supports it. The session is saved to Archive and can be re-exported with different settings at any time.

---

### Use Case 14 — Social Media Content in Multiple Aspect Ratios

You want to post the same event to TikTok (9:16 vertical), Instagram (1:1 square), and YouTube (16:9 widescreen) without re-editing three times.

**How:** Build your compilation once in EdgeVideo. Then export three times, each time with a different **Quality** preset. The current presets target 1920×1080 (HD) and 3840×2160 (4K) in 16:9. For platform-specific crops, edit the `scale` filter in the generated export script before running — change `scale=1920:1080` to `scale=1080:1920,setsar=1` for vertical, or `scale=1080:1080` for square. The generated PowerShell script is fully editable before execution.

---

### Use Case 15 — Archiving and Revisiting Old Projects

You exported a compilation months ago and now want to create a revised version with new clips added or different audio.

**How:** Open the **Archive** tab and find the old session. The thumbnail, duration, and metadata are all preserved. Play it back to remind yourself of the content. While you cannot directly edit a completed export, the session folder (`%USERPROFILE%\EdgeVideo\sessions\session_*\`) contains the original export script (`export.ps1`) and all uploaded assets. Copy the script, modify it, and re-run it — or start a new session and rebuild from the GWF clips using the Archive as a reference. This non-destructive approach means your original export is always preserved while new versions can be created alongside it.

---

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 21H2 | Windows 11 23H2+ |
| CPU | Any x86_64 with AVX2 | 8-core modern CPU |
| RAM | 8 GB | 16 GB+ |
| GPU VRAM | 6 GB (Ollama only) | 8 GB+ (Ollama + ComfyUI) |
| Storage | 15 GB free | 40 GB+ |
| Python | 3.10+ | 3.12 |
| FFmpeg | 5.0+ | 7.x (latest) |

---

## Dependencies

| Package | Purpose |
|---|---|
| `flask>=3.0` | HTTP server and REST API |
| `watchdog>=4.0` | GWF folder file-system watcher |
| `pystray>=0.19` | Windows system tray icon |
| `Pillow>=10.0` | Tray icon image generation |
| Ollama + `gemma4:e4b` | Local AI — clip analysis, scene descriptions |
| FFmpeg | Video encoding, trimming, concatenation, audio mixing |
| ComfyUI *(optional)* | AI video transition generation (LTX-Video 2B) |

---

## Installation

Run the included PowerShell script — it installs all dependencies automatically:

```powershell
# Right-click → Run with PowerShell, or:
powershell -ExecutionPolicy Bypass -File INSTALL_WINDOWS.ps1
```

See [INSTALL_WINDOWS.ps1](INSTALL_WINDOWS.ps1) for the full script.

---

## Configuration

On first launch EdgeVideo auto-generates `console_config.json` in `%USERPROFILE%\EdgeVideo\`. Edit via the **Settings** tab in the browser or directly in the JSON file:

```json
{
  "gwf_path": "C:\\Users\\you\\EdgeVideo\\gwf",
  "sessions_path": "C:\\Users\\you\\EdgeVideo\\sessions",
  "server_port": 8765,
  "comfyui_port": 8188,
  "ollama_port": 11434,
  "open_browser_on_start": true,
  "log_file": "C:\\Users\\you\\EdgeVideo\\console.log"
}
```

---

## Troubleshooting

**Console window appears but browser does not open**  
Check that port 8765 is not already in use. Change `server_port` in the config file.

**Tray icon is amber (not green)**  
ComfyUI is not running. This is normal if you have not installed ComfyUI. AI transitions will be unavailable but all other features work.

**Tray icon is red**  
FFmpeg was not found. Run `INSTALL_WINDOWS.ps1` to install it, or add it to your PATH manually.

**Gemma 4 analysis returns errors**  
Confirm Ollama is running (`ollama serve` in a terminal) and the model is pulled (`ollama list` should show `gemma4:e4b`).

**Export fails with ffmpeg error**  
Check the session's `export.log` and `export_err.log` in `%USERPROFILE%\EdgeVideo\sessions\session_*\`. The Dashboard live log also shows ffmpeg stderr output in real time.

**Save As downloads an HTML file**  
Reload the browser page (Ctrl+R) to pick up the latest version of the UI after a console update.

---

## License

EdgeVideo is released under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0).

Gemma 4 model weights are governed by the [Gemma Terms of Use](https://ai.google.dev/gemma/terms).  
LTX-Video model weights are governed by their respective Hugging Face licence terms.

---

*EdgeVideo · Local-first AI video production · Windows 11*
