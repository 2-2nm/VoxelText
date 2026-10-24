import ctypes
import sys
import threading
import time
from ctypes import wintypes
import platform
import numpy as np
import cv2

PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020

if platform.system() == "Windows":
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long)
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ('biSize', wintypes.DWORD),
            ('biWidth', wintypes.LONG),
            ('biHeight', wintypes.LONG),
            ('biPlanes', wintypes.WORD),
            ('biBitCount', wintypes.WORD),
            ('biCompression', wintypes.DWORD),
            ('biSizeImage', wintypes.DWORD),
            ('biXPelsPerMeter', wintypes.LONG),
            ('biYPelsPerMeter', wintypes.LONG),
            ('biClrUsed', wintypes.DWORD),
            ('biClrImportant', wintypes.DWORD)
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ('bmiHeader', BITMAPINFOHEADER),
            ('bmiColors', wintypes.DWORD * 3)
        ]

    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int


def list_active_windows():
    if platform.system() != "Windows":
        return []

    windows = []

    def enum_windows_callback(hwnd, extra):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()
                rect = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 100 and h > 100 and "VoxelText" not in title:
                    windows.append((hwnd, title))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
    return windows


IGNORED_EXECUTABLES = {
    "code.exe", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
    "explorer.exe", "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "python.exe", "pythonw.exe", "discord.exe", "telegram.exe", "spotify.exe", "slack.exe",
    "whatsapp.exe", "msteams.exe", "notepad.exe", "notepad++.exe", "devenv.exe", "idea64.exe",
    "pycharm64.exe", "applicationframehost.exe", "textinputhost.exe", "systemsettings.exe",
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "obs64.exe", "taskmgr.exe",
    "winword.exe", "excel.exe", "powerpnt.exe", "voxeltext.exe",
}


def get_window_executable(hwnd):
    if platform.system() != "Windows":
        return ""
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        pid = wintypes.DWORD(0)
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = k32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.replace("/", "\\").split("\\")[-1].lower()
        finally:
            k32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def guess_game_window(windows):
    best = None
    best_area = -1
    for hwnd, title in windows:
        if "minecraft" in title.lower():
            return hwnd
        if get_window_executable(hwnd) in IGNORED_EXECUTABLES:
            continue
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > best_area:
            best_area = area
            best = hwnd
    return best


def get_window_title(hwnd):
    if platform.system() != "Windows" or not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value


class GameCapture:
    def __init__(self, hwnd=None, target_title_keyword="Minecraft"):
        self.hwnd = hwnd
        self.target_keyword = target_title_keyword
        self._mfc_dc = None
        self._bitmap = None
        self._buffer = None
        self._bmpinfo = None
        self._size = (0, 0)
        if self.hwnd is None:
            self.find_window_by_keyword(self.target_keyword)

    def find_window_by_keyword(self, keyword):
        windows = list_active_windows()
        for h, title in windows:
            if keyword.lower() in title.lower():
                self.hwnd = h
                return h, title
        if windows:
            self.hwnd = windows[0][0]
            return windows[0][0], windows[0][1]
        self.hwnd = None
        return None, "No Window Found"

    def is_valid_hwnd(self):
        if platform.system() != "Windows" or not self.hwnd:
            return False
        return bool(user32.IsWindow(self.hwnd) and user32.IsWindowVisible(self.hwnd))

    def _release_gdi(self):
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
        if self._mfc_dc:
            gdi32.DeleteDC(self._mfc_dc)
        self._bitmap = None
        self._mfc_dc = None
        self._buffer = None
        self._size = (0, 0)

    def close(self):
        self._release_gdi()

    def _ensure_gdi(self, window_dc, width, height):
        if self._mfc_dc and self._size == (width, height):
            return
        self._release_gdi()
        self._mfc_dc = gdi32.CreateCompatibleDC(window_dc)
        self._bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        self._buffer = np.empty((height, width, 4), dtype=np.uint8)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        self._bmpinfo = bmi
        self._size = (width, height)

    def capture_frame(self):
        if not self.is_valid_hwnd():
            return None

        client_rect = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(client_rect))
        width = client_rect.right - client_rect.left
        height = client_rect.bottom - client_rect.top

        if width <= 0 or height <= 0:
            window_rect = RECT()
            user32.GetWindowRect(self.hwnd, ctypes.byref(window_rect))
            width = window_rect.right - window_rect.left
            height = window_rect.bottom - window_rect.top

        if width <= 0 or height <= 0:
            return None

        window_dc = user32.GetWindowDC(self.hwnd)
        if not window_dc:
            return None

        try:
            self._ensure_gdi(window_dc, width, height)
            old_bitmap = gdi32.SelectObject(self._mfc_dc, self._bitmap)

            printed = user32.PrintWindow(self.hwnd, self._mfc_dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
            if not printed:
                printed = user32.PrintWindow(self.hwnd, self._mfc_dc, PW_CLIENTONLY)
            if not printed:
                gdi32.BitBlt(self._mfc_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY)

            gdi32.SelectObject(self._mfc_dc, old_bitmap)
            gdi32.GetDIBits(
                self._mfc_dc, self._bitmap, 0, height,
                self._buffer.ctypes.data, ctypes.byref(self._bmpinfo), 0
            )
        finally:
            user32.ReleaseDC(self.hwnd, window_dc)

        return cv2.cvtColor(self._buffer, cv2.COLOR_BGRA2RGB)


class FrameSource:
    def __init__(self, hwnd, prefer_wgc=True, log_cb=None):
        self.hwnd = hwnd
        self.prefer_wgc = prefer_wgc
        self.log_cb = log_cb
        self.backend = None
        self._pw = GameCapture(hwnd=hwnd)
        self._cond = threading.Condition()
        self._frame = None
        self._frame_id = 0
        self._stop = threading.Event()
        self._thread = None
        self._wgc_control = None
        self._cb_acc = 0.0
        self._cb_n = 0
        self._cb_max = 0.0

    def _log(self, text, tag="info"):
        if self.log_cb:
            self.log_cb(text, tag)

    def is_valid(self):
        return self._pw.is_valid_hwnd()

    @property
    def total_frames(self):
        return self._frame_id

    def _publish(self, rgb):
        with self._cond:
            self._frame = rgb
            self._frame_id += 1
            self._cond.notify_all()

    def wait_frame(self, last_id, timeout=0.05):
        with self._cond:
            if self._frame_id == last_id:
                self._cond.wait(timeout)
            if self._frame_id != last_id and self._frame is not None:
                return self._frame, self._frame_id
        return None, last_id

    def start(self):
        if self.prefer_wgc and platform.system() == "Windows":
            if self._start_wgc():
                self.backend = "WGC"
                return
        self._start_printwindow()
        self.backend = "PrintWindow"

    def _start_wgc(self):
        try:
            from windows_capture import WindowsCapture
        except Exception:
            self._log("windows-capture not installed (pip install windows-capture); using slow PrintWindow capture.", "warn")
            return False
        try:
            sys.setswitchinterval(0.001)
        except Exception:
            pass

        title = get_window_title(self.hwnd)
        base = dict(cursor_capture=False, draw_border=False)
        attempts = [
            dict(window_hwnd=int(self.hwnd), minimum_update_interval=1, **base),
            dict(window_hwnd=int(self.hwnd), **base),
            dict(window_hwnd=int(self.hwnd)),
            dict(window_name=title, **base),
            dict(window_name=title),
        ]

        source = self

        for kwargs in attempts:
            try:
                cap = WindowsCapture(**kwargs)

                @cap.event
                def on_frame_arrived(frame, capture_control):
                    t0 = time.perf_counter()
                    if source._stop.is_set():
                        try:
                            capture_control.stop()
                        except Exception:
                            pass
                        return
                    buf = frame.frame_buffer
                    if buf is None or buf.ndim != 3:
                        return
                    source._publish(cv2.cvtColor(buf, cv2.COLOR_BGRA2RGB))
                    dt = time.perf_counter() - t0
                    source._cb_acc += dt
                    source._cb_n += 1
                    if dt > source._cb_max:
                        source._cb_max = dt

                @cap.event
                def on_closed():
                    pass

                self._wgc_control = cap.start_free_threaded()
            except Exception as e:
                self._wgc_control = None
                self._log(f"WGC attempt {sorted(kwargs)} failed: {e}", "warn")
                continue

            deadline = time.perf_counter() + 2.0
            while time.perf_counter() < deadline:
                frame, _ = self.wait_frame(0, 0.1)
                if frame is not None:
                    self._log("WGC options: " + ", ".join(k for k in kwargs if k != "window_name" and k != "window_hwnd"), "info")
                    return True

            self._log("WGC delivered no frames; falling back to PrintWindow.", "warn")
            self._stop_wgc()
            return False

        return False

    def pop_cb_stats(self):
        n = max(self._cb_n, 1)
        avg, mx = 1000.0 * self._cb_acc / n, 1000.0 * self._cb_max
        self._cb_acc, self._cb_n, self._cb_max = 0.0, 0, 0.0
        return avg, mx

    def _stop_wgc(self):
        ctrl, self._wgc_control = self._wgc_control, None
        if ctrl is not None:
            try:
                ctrl.stop()
            except Exception:
                pass

    def _start_printwindow(self):
        def loop():
            try:
                while not self._stop.is_set():
                    frame = self._pw.capture_frame()
                    if frame is None:
                        time.sleep(0.01)
                        continue
                    self._publish(frame)
            finally:
                self._pw.close()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._stop_wgc()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
