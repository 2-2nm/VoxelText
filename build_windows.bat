@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === VoxelText build ===

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller || goto :fail
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

set "ICON="
if exist "assets\app-icon.ico" set "ICON=--icon assets\app-icon.ico"

set "EXTRA="
for %%P in (moderngl glcontext imageio_ffmpeg windows_capture pywinstyles pygame) do (
    python -c "import %%P" >nul 2>nul && set "EXTRA=!EXTRA! --collect-all %%P"
)

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name VoxelText ^
    %ICON% ^
    --add-data "assets;assets" ^
    !EXTRA! ^
    main.py
if errorlevel 1 goto :fail

echo.
echo Build OK: dist\VoxelText.exe
exit /b 0

:fail
echo.
echo Build FAILED.
exit /b 1
