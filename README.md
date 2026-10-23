# VoxelText

![Python](https://img.shields.io/badge/PYTHON-3.8--3.13-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=4a4f57)
![GUI](https://img.shields.io/badge/GUI-PYSIDE6-41CD52?style=for-the-badge&logo=qt&logoColor=white&labelColor=4a4f57)
![Renderer](https://img.shields.io/badge/RENDERER-MODERNGL%20%2F%20OPENGL%203.3-5586A4?style=for-the-badge&logo=opengl&logoColor=white&labelColor=4a4f57)
![Platform](https://img.shields.io/badge/PLATFORM-WINDOWS%2010%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white&labelColor=4a4f57)
![License](https://img.shields.io/badge/LICENSE-MIT-9ACD32?style=for-the-badge&labelColor=4a4f57)

A desktop app that converts photos and video into ASCII art, **rendered on the GPU in real time**. The ASCII grid is drawn by OpenGL fragment shaders (ModernGL), so even a 2000-column video plays back smoothly with synced audio. Finished videos can be exported as **MP4 (with the original audio)**.

<p align="center">
  <img width="426" height="240" alt="1021" src="https://github.com/user-attachments/assets/b8780dd1-218e-4d0d-ad8b-d804c2e0a963" />


</p>

<p align="center"><b>That is not a video, it's text.</b> A game clip rendered at 2000 columns in real time.</p>

<p align="center">
  <a href="https://youtu.be/_bCFDKqHmSQ"><img src="https://img.shields.io/badge/WATCH-DEMO%20VIDEO-FF0000?style=for-the-badge&logo=youtube&logoColor=white&labelColor=4a4f57" alt="Watch the demo video"></a>
</p>

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

- **Image to ASCII** with 11 single-color palettes (Green, Monochrome, Red, Pink, Coral, Amber, Lime, Cyan, Violet, Blue, Ember), plus a **Full Color** mode
- **Two Full Color styles**: *Blocky* (solid `█` blocks tinted with the source color) and *Pure ASCII* (real characters)
- **Video to ASCII in real time**, with audio, pause, stop, seek (timeline) and mute
- **Export video as MP4**: renders the ASCII video with the GPU and encodes it with FFmpeg (H.264 + AAC), keeping the source audio
- **Two transparency modes**: *White* (bright areas become transparent) and *Black* (dark areas become transparent)
- **Adjustable width**: 30-200 columns for images, 30-500 for video, or tick **Overdrive** and type a custom value (e.g. 2000+)
- **Export images** as high-resolution PNG (at least 2560 px wide) or as a plain `.txt` file
- **Command-line mode** for quick image to TXT conversion (no GUI needed)
- Dark / Light theme, fullscreen (`F11`), a live console log panel and a collapsible settings deck
- Your settings (theme, palette, width, Overdrive, etc.) are saved automatically between sessions

## How it works

1. Each frame is split into a grid of cells, one per character.
2. Brightness (`0.299R + 0.587G + 0.114B`) picks which character a cell uses.
3. All characters are drawn once into a **glyph atlas** texture; the fragment shader just samples the right slice.
4. **Two render passes**: pass 1 builds the full-resolution ASCII grid, pass 2 downsamples it to fit the preview.
5. **Audio is the master clock.** Audio is extracted with FFmpeg and played with pygame; late frames are skipped, early frames wait.
6. In Full Color mode, colors are quantized to 5-6-5 bits per channel for a retro look.
7. **MP4 export** reuses pass 1 at full resolution, pipes the raw frames into FFmpeg, and muxes the audio of the source video. If FFmpeg is not available, it falls back to OpenCV's `mp4v` writer (video only, no audio).

> Note: In Full Color mode with the **Blocky** style, every cell is a solid block (`█`) tinted with the source color. Choose **Pure ASCII** to draw real characters (`@ # S % ? * + ; : , .`) in color instead. The single-color palettes always use real characters.

## Requirements

- Windows 10 / 11 and Python 3.8 - 3.13 (Python 3.14 is not supported by the build script)
- A GPU with OpenGL 3.3 support
- Packages: `PySide6`, `moderngl`, `numpy`, `opencv-python`, `Pillow`, `pygame-ce`, `imageio-ffmpeg` (or a system `ffmpeg` on your PATH)
- Optional: `psutil` (system info in the startup screen) and `pywinstyles` (dark title bar on Windows)

## Installation

```bash
git clone https://github.com/2-2nm/VoxelText-ASCII-.git
cd VoxelText-ASCII-
pip install PySide6 Pillow numpy opencv-python moderngl pygame-ce psutil pywinstyles imageio-ffmpeg
python main.py
```

### Build a standalone .exe (Windows)

Put all source files (and optional assets such as `app-icon.ico`, `ascii_terminal.txt`, the icon PNGs or a `data` folder) in the same directory, then run:

```bat
build_windows.bat
```

The script finds a compatible Python, installs the dependencies, and builds a single windowed executable with PyInstaller. The result is saved to `dist\VoxelText.exe`.

## Usage

### GUI

1. Open the **Image** or **Video** tab and load a file.
2. Pick a palette (**Full Color** or a single color), a Full Color style (**Blocky** / **Pure ASCII**) and a transparency mode.
3. Drag the **Width** slider. For very high resolution, tick **Overdrive** and type a value (e.g. `2000`).
4. For video, use **Pause** / **Stop**, the timeline to seek, and the speaker button to mute.
5. Click **Save as PNG** (image tab) or **Save as MP4** (video tab) to export your result.

Shortcuts: `F11` toggles fullscreen, `Esc` leaves fullscreen, and the arrow keys scroll the text preview.

Tip: the difference between 200 and 2000 columns is easiest to see on a big screen.

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
| `--version`, `-v` | Show the version (v2.6.0) |

Running `python main.py` with no arguments starts the GUI.

## Project structure

| File | Purpose |
|---|---|
| `main.py` | Entry point (CLI arguments, GPU selection, launches the GUI) |
| `gui.py` | PySide6 GUI (themes, settings, image/video tabs, console log) |
| `core.py` | Image pipeline, shaders, glyph atlas, PNG/TXT export |
| `core_v.py` | GPU video player (frame loop, A/V sync) |
| `audio_player.py` | Audio extraction (FFmpeg) and playback (pygame) |
| `video_exporter.py` | ASCII video to MP4 export (GPU render + FFmpeg encode) |
| `build_windows.bat` | One-click Windows build script (PyInstaller) |

Settings are stored in `%APPDATA%\VoxelText\settings.json`.

## Known limitations

- The **Cutoff** slider is not wired up yet and has no effect.
- Frames are read back from the GPU to the CPU for display and export, so total load is not 100% on the GPU.
- MP4 export is re-rendered from the source video and is not real time; long videos at very high widths take a while.

## Credits

Built with Python, PySide6, OpenCV, ModernGL, pygame, FFmpeg and Pillow.

## License

MIT, see [LICENSE](LICENSE).
