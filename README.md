# VoxelText

![Version](https://img.shields.io/badge/VERSION-3.0.0-FF6B6B?style=for-the-badge&labelColor=4a4f57)
![Python](https://img.shields.io/badge/PYTHON-3.8--3.13-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=4a4f57)
![GUI](https://img.shields.io/badge/GUI-PYSIDE6-41CD52?style=for-the-badge&logo=qt&logoColor=white&labelColor=4a4f57)
![Renderer](https://img.shields.io/badge/RENDERER-MODERNGL%20%2F%20OPENGL%203.3-5586A4?style=for-the-badge&logo=opengl&logoColor=white&labelColor=4a4f57)
![Platform](https://img.shields.io/badge/PLATFORM-WINDOWS%2010%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white&labelColor=4a4f57)
![License](https://img.shields.io/badge/LICENSE-MIT-9ACD32?style=for-the-badge&labelColor=4a4f57)

A desktop app that turns photos, videos and **live games** into ASCII art, **rendered on the GPU in real time**. The ASCII grid is drawn by OpenGL fragment shaders (ModernGL), so even a 2000-column video plays back smoothly with synced audio, and a running game can be streamed through the same pipeline while you keep playing it.

<p align="center">
  <img width="384" height="240" alt="gameascii" src="https://github.com/user-attachments/assets/1fdb07a8-e678-4669-9f34-390653a33382" />

  <img width="384" height="240" alt="gameascii(1)" src="https://github.com/user-attachments/assets/26ccdddc-cd28-4820-b24e-b28f3a4dfc70" />

  <img width="384" height="240" alt="gameasciir" src="https://github.com/user-attachments/assets/670942e1-fcd1-467f-9d31-0cb88e66b1ba" />

</p>

<p align="center"><b>That is not a video, it's text.</b> Minecraft played live through Game Stream.</p>

<p align="center">
  <a href="https://youtu.be/_bCFDKqHmSQ"><img src="https://img.shields.io/badge/WATCH-DEMO%20VIDEO-FF0000?style=for-the-badge&logo=youtube&logoColor=white&labelColor=4a4f57" alt="Watch the demo video"></a>
</p>

## What's new in 3.0.0

- **Game Stream (new):** pick any running game window and play it as live ASCII art on the GPU
- **Playable overlay:** the ASCII picture is shown on a click-through overlay, so mouse and keyboard still go straight to the game
- **Glyph sets:** six selectable character sets (Standard, Fine, Classic, Blocks, Minimal, Digits), each sorted by measured ink density
- **Better tone and color:** shadow lifting, fading of dark glyphs and a color boost for Pure ASCII
- **Sharper downscaling:** area-averaged sampling through mipmaps, plus a tonal fallback when cells are too small to show glyph shapes
- **Reorganized project:** the code now lives in `core/`, `ui/`, `video/` and `game/` packages, and the build script bundles an `assets/` folder

## Game Stream

Game Stream captures a window and converts every frame to ASCII on the GPU, live. It is built for low latency rather than for recording.

- **Pick a window** from the list of open windows and start streaming
- **Live render** with the same shaders, palettes, Full Color styles, transparency modes and glyph sets as image and video
- **Engage mode** moves the game window under the preview, makes it borderless, and keeps it aligned when you resize the preview. Everything is restored to the original size, position and style when you stop
- **Click-through overlay:** a topmost, non-activating window displays the ASCII frames over the game, so you see ASCII but your input still reaches the game
- **Focus handling:** the game is brought to the foreground automatically. If Windows refuses, click the stream preview to take control
- **Live FPS counter** and a periodic `[perf]` line in the console log (capture fps, render fps, idle wait, GPU work time, grid size)
- **Smart readback:** a double-buffered pixel buffer overlaps GPU work with the CPU copy, and the render resolution is capped when the preview is small
- **Legibility warning:** the log tells you when the chosen width gives fewer than about 4 pixels per character, and suggests a width that fits
- **Minecraft helper:** the app sets `pauseOnLostFocus:false` in `.minecraft/options.txt` so the game does not pause when it loses focus (applies on the next game launch)

### Playing a game through Game Stream

1. Start your game in **windowed** or **borderless** mode.
2. Open the **Game** tab and select the game window.
3. Choose a palette, a Full Color style and a width. For games, **Pure ASCII** with a moderate width (about 150 to 250 columns) gives the most readable result.
4. Start the stream. Engage the overlay to play the game while seeing it as ASCII.
5. Stop the stream to restore the game window to its original place.

## Screenshots

<p align="center">
  <img width="49%" height="873" alt="Screenshot (1453)" src="https://github.com/user-attachments/assets/1f578592-8929-46f1-92a6-bbbb50ce8bef" />
  <img width="49%" height="859" alt="Screenshot (1454)" src="https://github.com/user-attachments/assets/e1e53a14-3272-4cc5-b408-029c5e0f8728" />
</p>
<p align="center"><i>Image mode: palettes and transparency modes (left: Red, right: Monochrome + White transparency)</i></p>

<p align="center">
  <img width="1495" height="868" alt="Screenshot (1452)" src="https://github.com/user-attachments/assets/543bc586-3b53-489a-b244-22989bb3c650" />
</p>
<p align="center"><i>Startup screen</i></p>

## Features

- **Game to ASCII in real time**, with a click-through overlay so you can keep playing
- **Image to ASCII** with 11 single-color palettes (Green, Monochrome, Red, Pink, Coral, Amber, Lime, Cyan, Violet, Blue, Ember), plus a **Full Color** mode
- **Two Full Color styles**: *Blocky* (solid `█` blocks tinted with the source color) and *Pure ASCII* (real characters)
- **Six glyph sets**: Standard, Fine, Classic, Blocks, Minimal and Digits
- **Video to ASCII in real time**, with audio, pause, stop, seek (timeline) and mute
- **Export video as MP4**: renders the ASCII video on the GPU and encodes it with FFmpeg (H.264 + AAC), keeping the source audio
- **Two transparency modes**: *White* (bright areas become transparent) and *Black* (dark areas become transparent)
- **Adjustable width**: 30-200 columns for images, 30-500 for video, or tick **Overdrive** and type a custom value (e.g. 2000+)
- **Export images** as high-resolution PNG (at least 2560 px wide) or as a plain `.txt` file
- **Command-line mode** for quick image to TXT conversion (no GUI needed)
- Dark / Light theme, fullscreen (`F11`), a live console log panel and a collapsible settings deck
- Your settings (theme, palette, width, Overdrive, etc.) are saved automatically between sessions

## How it works

1. Each frame is split into a grid of cells, one per character.
2. Each cell is sampled with mipmaps, so it receives the average color of the area it covers instead of a single pixel.
3. Brightness (`0.299R + 0.587G + 0.114B`), shaped by a tone curve, picks which glyph a cell uses.
4. All glyphs are drawn once into a **glyph atlas** texture; the fragment shader just samples the right slice. When a cell is too small to show a glyph shape, the shader uses the glyph's average ink coverage instead, which avoids stripe aliasing.
5. **Two render passes**: pass 1 builds the full-resolution ASCII grid, pass 2 downsamples it to fit the preview.
6. **Glyph sets** are ranked by the measured ink density of each character in the real font, so the ramp from light to dense is always even.
7. **Video:** audio is the master clock. Audio is extracted with FFmpeg and played with pygame; late frames are skipped, early frames wait.
8. **Game:** frames arrive from the window capture source. Only new frames trigger a render, and the result is read back through a double-buffered pixel buffer.
9. In Full Color mode, colors are quantized to 5-6-5 bits per channel for a retro look.
10. **MP4 export** reuses pass 1 at full resolution, pipes the raw frames into FFmpeg, and muxes the audio of the source video. If FFmpeg is not available, it falls back to OpenCV's `mp4v` writer (video only, no audio).

> Note: In Full Color mode with the **Blocky** style, every cell is a solid block (`█`) tinted with the source color. Choose **Pure ASCII** to draw real characters in color instead. The single-color palettes always use real characters.

## Requirements

- Windows 10 / 11 and Python 3.8 - 3.13
- A GPU with OpenGL 3.3 support
- Packages: `PySide6`, `moderngl`, `numpy`, `opencv-python`, `Pillow`, `pygame-ce`, `imageio-ffmpeg` (or a system `ffmpeg` on your PATH)
- Optional: `windows-capture` (window capture for Game Stream), `psutil` (system info on the startup screen) and `pywinstyles` (dark title bar on Windows)

## Installation

```bash
git clone https://github.com/2-2nm/VoxelText-ASCII-.git
cd VoxelText-ASCII-
pip install PySide6 Pillow numpy opencv-python moderngl pygame-ce imageio-ffmpeg windows-capture psutil pywinstyles
python main.py
```

### Build a standalone .exe (Windows)

Keep the project folder structure as is. Optional assets such as `app-icon.ico` go in the `assets` folder. Then run:

```bat
build_windows.bat
```

The script installs PyInstaller if needed, bundles the `assets` folder together with the native files of every optional package that is installed, and builds a single windowed executable. The result is saved to `dist\VoxelText.exe`.

## Usage

### GUI

1. Open the **Image**, **Video** or **Game** tab.
2. Load a file, or pick a game window.
3. Pick a palette (**Full Color** or a single color), a Full Color style (**Blocky** / **Pure ASCII**), a glyph set and a transparency mode.
4. Drag the **Width** slider. For very high resolution, tick **Overdrive** and type a value (e.g. `2000`).
5. For video, use **Pause** / **Stop**, the timeline to seek, and the speaker button to mute.
6. Click **Save as PNG** (image tab) or **Save as MP4** (video tab) to export your result.

Shortcuts: `F11` toggles fullscreen, `Esc` leaves fullscreen, and the arrow keys scroll the text preview.

Tip: the difference between 200 and 2000 columns is easiest to see on a big screen. For live games, a lower width is usually more readable.

### Command line

Convert an image to ASCII text without opening the GUI:

```bash
python main.py --image photo.jpg --output photo_ascii.txt --width 120
```

| Option | Description |
|---|---|
| `--image`, `-i` | Input image file |
| `--output`, `-o` | Output TXT file (prints to the console if omitted) |
| `--width`, `-w` | Number of ASCII columns (default: 85) |
| `--version`, `-v` | Show the version (v3.0.0) |

Running `python main.py` with no arguments starts the GUI.

## Project structure

| Path | Purpose |
|---|---|
| `main.py` | Entry point (CLI arguments, high-performance GPU hint, launches the GUI) |
| `core/ascii.py` | Shaders, glyph atlas, glyph sets, image pipeline, PNG/TXT export |
| `core/utils.py` | Resource lookup, config location, color helpers |
| `ui/gui.py` | PySide6 GUI (themes, settings, image/video/game tabs, console log) |
| `ui/overlay.py` | Click-through game overlay window and the segmented button widget |
| `video/player.py` | GPU video player (frame loop, A/V sync, seek) |
| `video/audio.py` | Audio extraction (FFmpeg) and playback (pygame) |
| `video/exporter.py` | ASCII video to MP4 export (GPU render + FFmpeg encode) |
| `game/capture.py` | Game window capture and frame source |
| `game/player.py` | GPU game player (live render loop, FPS and performance stats) |
| `game/manager.py` | Window management: borderless mode, placement, focus, restore |
| `build_windows.bat` | One-click Windows build script (PyInstaller) |
| `assets/` | Icons and other bundled resources |

Settings are stored in `%APPDATA%\VoxelText\settings.json`.

## Known limitations

- Game Stream is Windows only.
- Games that run in exclusive fullscreen may not be capturable. Use windowed or borderless mode.
- Games with anti-cheat protection may block window capture or window changes. Use Game Stream only with games where this is allowed.
- Engage mode changes the style and position of the game window while streaming. It is restored when you stop, but if the app is killed unexpectedly the game window may need a restart to return to normal.
- To focus the game reliably, the app relaxes the Windows foreground lock timeout for the current session.
- Frames are read back from the GPU to the CPU for display and export, so total load is not 100% on the GPU.
- MP4 export is re-rendered from the source video and is not real time; long videos at very high widths take a while.

## Credits

Built with Python, PySide6, OpenCV, ModernGL, pygame, FFmpeg and Pillow.

## License

MIT, see [LICENSE](LICENSE).
