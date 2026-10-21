# VoxelText

**Turn images and videos into ASCII art, rendered on the GPU in real time.**

![VoxelText demo](docs/thumbnail.png)

> Demo video: [YOUR VIDEO LINK HERE]

VoxelText is a desktop app (Python + PySide6) that converts photos and video into text characters. The ASCII grid is drawn by OpenGL fragment shaders (ModernGL), so even a 2000-column video plays back smoothly with synced audio.

## Features

- **Image to ASCII** with 12 color palettes, plus a **Full Color** mode
- **Video to ASCII in real time**, with audio, pause, seek (timeline) and mute
- **Two transparency modes**: *White* (bright areas become transparent) and *Black* (dark areas become transparent)
- **Adjustable width** (30-200 columns), or type a custom value with **Overdrive** for 2000+ columns
- **Export as PNG**, high resolution, so you can zoom in and see every character
- Dark / Light theme and a live console log panel

## How it works

1. Each frame is split into a grid of cells, one per character.
2. Brightness (`0.299R + 0.587G + 0.114B`) picks which character a cell uses.
3. All characters are drawn once into a **glyph atlas** texture; the fragment shader just samples the right slice.
4. **Two render passes**: pass 1 builds the full-resolution ASCII grid, pass 2 downsamples it to fit the preview.
5. **Audio is the master clock.** Audio is extracted with FFmpeg and played with pygame; late frames are skipped, early frames wait.
6. In Full Color mode, colors are quantized to 5-6-5 bits per channel for a retro look.

> Note: Full Color mode draws a solid block character (`█`) per cell, tinted with the source color. The monochrome and single-color palettes use real characters (`@ # S % ? * + ; : , .`). Want letters in Full Color too? Edit `ASCII_CHARS_COLOR_BLACK_BG` in `core.py`.

## Requirements

- Python 3.10+
- A GPU with OpenGL 3.3 support
- Packages: `PySide6`, `moderngl`, `numpy`, `opencv-python`, `Pillow`, `pygame`, `imageio-ffmpeg` (or a system `ffmpeg` on your PATH)

## Installation

```bash
git clone https://github.com/2-2nm/VoxelText-ASCII-.git
cd VoxelText-ASCII-
pip install PySide6 moderngl numpy opencv-python Pillow pygame imageio-ffmpeg
python terminal-ui.py
```

## Usage

1. Open the **Image** or **Video** tab and load a file.
2. Pick a palette (**Full Color** or **Monochrome**) and a transparency mode.
3. Drag the **Width** slider. For very high resolution, tick **Overdrive** and type a value (e.g. `2000`).
4. For video, use the timeline to seek and the speaker button to mute.
5. Save your result as a PNG from the image tab.

Tip: the difference between 200 and 2000 columns is easiest to see on a big screen.

## Project structure

| File | Purpose |
|---|---|
| `terminal-ui.py` | PySide6 GUI (entry point) |
| `core.py` | Image pipeline, shaders, glyph atlas, PNG export |
| `core_v.py` | GPU video player (frame loop, A/V sync) |
| `audio_player.py` | Audio extraction (FFmpeg) and playback (pygame) |

## Known limitations

- The **Cutoff** slider is not wired up yet and has no effect.
- Frames are read back from the GPU to the CPU for display, so total load is not 100% on the GPU.

## Credits

Built with Python, PySide6, OpenCV, ModernGL, pygame, FFmpeg and Pillow.

## License

MIT, see [LICENSE](LICENSE).
