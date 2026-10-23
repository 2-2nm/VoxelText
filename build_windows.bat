@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for /f "delims=" %%A in ('powershell -NoProfile -Command "[char]27"') do set "ESC=%%A"
set "RED=%ESC%[91m"
set "GREEN=%ESC%[92m"
set "RESET=%ESC%[0m"

echo ========================================================
echo           VoxelText Windows Build Tool
echo ========================================================
echo.

for %%F in (main.py gui.py core.py core_v.py audio_player.py video_exporter.py) do (
if not exist "%%F" (
echo %RED%[ERROR] Source file not found: %%F%RESET%
echo %RED%Please place all Python source files in this directory.%RESET%
goto :fail
)
)

set "PY="

where py >nul 2>&1
if not errorlevel 1 (
for %%V in (3.13 3.12 3.11 3.10 3.9 3.8) do (
if not defined PY (
py -%%V -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -%%V"
)
)
)

if not defined PY (
where python >nul 2>&1
if not errorlevel 1 (
python -c "import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)" >nul 2>&1
if not errorlevel 1 (
set "PY=python"
)
)
)

if not defined PY (
echo %RED%[ERROR] Python 3.8 - 3.13 was not detected!%RESET%
echo %RED%Please install Python from https://www.python.org/downloads/%RESET%
pause
exit /b 1
)

echo [INFO] Using Python environment: %PY%
echo.

echo [INFO] Installing / updating dependencies...
%PY% -m pip install --upgrade PySide6 Pillow numpy opencv-python moderngl pygame-ce psutil pywinstyles imageio-ffmpeg pyinstaller
if errorlevel 1 (
echo %RED%[ERROR] Failed to install Python dependencies.%RESET%
goto :fail
)

echo.
echo [INFO] Detecting icons and assets...

set "DATA_ARGS="
if exist "data" set "DATA_ARGS=%DATA_ARGS% --add-data data;data"
if exist "app-icon.ico" set "DATA_ARGS=%DATA_ARGS% --add-data app-icon.ico;."
if exist "ascii_terminal.txt" set "DATA_ARGS=%DATA_ARGS% --add-data ascii_terminal.txt;."
if exist "clear_ascii.png" set "DATA_ARGS=%DATA_ARGS% --add-data clear_ascii.png;."
if exist "clear_ascii_l.png" set "DATA_ARGS=%DATA_ARGS% --add-data clear_ascii_l.png;."
if exist "mute.png" set "DATA_ARGS=%DATA_ARGS% --add-data mute.png;."
if exist "mute_l.png" set "DATA_ARGS=%DATA_ARGS% --add-data mute_l.png;."
if exist "unmute.png" set "DATA_ARGS=%DATA_ARGS% --add-data unmute.png;."
if exist "unmute_l.png" set "DATA_ARGS=%DATA_ARGS% --add-data unmute_l.png;."

set "ICON_ARG="
if exist "data\app-icon.ico" (
set "ICON_ARG=--icon data\app-icon.ico"
) else if exist "app-icon.ico" (
set "ICON_ARG=--icon app-icon.ico"
)

echo.
echo [INFO] Compiling VoxelText.exe ...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
--name VoxelText %ICON_ARG% %DATA_ARGS% ^
--collect-submodules PySide6 ^
--collect-submodules moderngl ^
--hidden-import pygame.mixer ^
--hidden-import psutil ^
--hidden-import pywinstyles ^
--hidden-import imageio_ffmpeg ^
--hidden-import PIL.Image ^
--hidden-import PIL.ImageDraw ^
--hidden-import PIL.ImageFont ^
--hidden-import cv2 ^
--hidden-import core ^
--hidden-import core_v ^
--hidden-import audio_player ^
--hidden-import video_exporter ^
--hidden-import gui ^
main.py

if errorlevel 1 goto :fail

echo.
echo %GREEN%%RESET%
echo %GREEN%[SUCCESS] Build succeeded!%RESET%
echo %GREEN%File location: %cd%\dist\VoxelText.exe%RESET%
echo %GREEN%%RESET%
echo.
pause
exit /b 0

:fail
echo.
echo %RED%%RESET%
echo %RED%[ERROR] Build failed. Please check the error messages above.%RESET%
echo %RED%%RESET%
echo.
pause
exit /b 1
