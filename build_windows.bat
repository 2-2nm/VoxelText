@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for %%F in (pyside6.py core.py core_v.py audio_player.py) do (
    if not exist "%%F" (
        echo Missing file: %%F
        echo Put all .py files in the same folder as this .bat.
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
    echo Python version below 3.14 was not found!
    echo Please install Python 3.13 or 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing dependencies...
%PY% -m pip install --upgrade PySide6 Pillow numpy opencv-python moderngl pygame-ce psutil pywinstyles imageio-ffmpeg pyinstaller
if errorlevel 1 goto :fail

set "DATA_ARGS="
if exist "app-icon.ico" set "DATA_ARGS=%DATA_ARGS% --add-data app-icon.ico;."
if exist "ascii_terminal.txt" set "DATA_ARGS=%DATA_ARGS% --add-data ascii_terminal.txt;."
if exist "clear_ascii.png" set "DATA_ARGS=%DATA_ARGS% --add-data clear_ascii.png;."
if exist "clear_ascii_l.png" set "DATA_ARGS=%DATA_ARGS% --add-data clear_ascii_l.png;."
if exist "mute.png" set "DATA_ARGS=%DATA_ARGS% --add-data mute.png;."
if exist "mute_l.png" set "DATA_ARGS=%DATA_ARGS% --add-data mute_l.png;."
if exist "unmute.png" set "DATA_ARGS=%DATA_ARGS% --add-data unmute.png;."
if exist "unmute_l.png" set "DATA_ARGS=%DATA_ARGS% --add-data unmute_l.png;."

set "ICON_ARG="
if exist "app-icon.ico" set "ICON_ARG=--icon app-icon.ico"

echo Building dist\VoxelText.exe ...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name VoxelText %ICON_ARG% %DATA_ARGS% --collect-submodules PySide6 --collect-submodules moderngl --hidden-import pygame.mixer --hidden-import psutil --hidden-import pywinstyles --hidden-import imageio_ffmpeg --hidden-import PIL.Image --hidden-import PIL.ImageDraw --hidden-import PIL.ImageFont --hidden-import cv2 --hidden-import core --hidden-import core_v --hidden-import audio_player pyside6.py
if errorlevel 1 goto :fail

echo.
echo Built: %cd%\dist\VoxelText.exe
echo.
pause
exit /b 0

:fail
echo.
echo Build failed. See the messages above.
pause
exit /b 1