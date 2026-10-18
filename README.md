# VoxelText

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PySide6]((https://img.shields.io/badge/GUI-PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![OpenGL](https://img.shields.io/badge/Graphics-ModernGL%20%2F%20OpenGL-555555?style=for-the-badge&logo=opengl&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)

**VoxelText** is a high-performance desktop suite built for converting images and real-time video into detailed ASCII art and ANSI color representations. Powered by GPU fragment shaders (ModernGL) and multi-core CPU processing, it offers smooth video-to-ASCII playback with audio synchronization, high-res export, and a retro terminal interface.

---

##  Key Features

- **GPU Offscreen Rendering:** Shader-based real-time image and video conversion using ModernGL & OpenGL 3.3.
- **Video & Audio Synchronization:** Real-time video-to-ASCII playback with synchronized audio extraction.
- **Multi-Core CPU Engine:** `ProcessPoolExecutor` fallback rendering for maximum multi-threading performance.
- **Rich Palette Selector:** Presets including *Matrix Green*, *Full Color*, *Cyber Cyan*, *Neon Pink*, *Monochrome*, and more.
- **Overdrive Width Mode:** Custom resolution override allowing high-density ASCII rendering beyond standard slider limits.
- **High-Res PNG Export:** Export ASCII results directly into high-resolution images up to 4K.

---

##  Installation & Setup

### Prerequisites
- Python 3.10 or higher
- OpenGL 3.3 compatible GPU

### 1. Clone the Repository
```bash
git clone [https://github.com/2-2nm/VoxelText.git](https://github.com/2-2nm/VoxelText.git)
cd VoxelText
