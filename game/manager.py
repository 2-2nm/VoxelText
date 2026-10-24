import os
import time
import ctypes
import platform
from ctypes import wintypes

IS_WINDOWS = platform.system() == "Windows"

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200

SW_HIDE = 0
SW_RESTORE = 9
SW_SHOWNOACTIVATE = 4

LWA_ALPHA = 0x00000002
SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
SPIF_SENDCHANGE = 0x0002

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    _set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    _get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_long.restype = ctypes.c_ssize_t
    _set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _set_long.restype = ctypes.c_ssize_t

    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    HWND_TOPMOST = wintypes.HWND(-1)
    HWND_NOTOPMOST = wintypes.HWND(-2)


def disable_minecraft_auto_pause():
    if not IS_WINDOWS:
        return False
    appdata = os.getenv("APPDATA")
    if not appdata:
        return False
    mc_options = os.path.join(appdata, ".minecraft", "options.txt")
    if not os.path.exists(mc_options):
        return False

    try:
        lines = []
        modified = False
        with open(mc_options, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("pauseOnLostFocus:"):
                    lines.append("pauseOnLostFocus:false\n")
                    modified = True
                else:
                    lines.append(line)

        if not modified:
            lines.append("pauseOnLostFocus:false\n")

        with open(mc_options, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False


def client_origin(hwnd):
    if not IS_WINDOWS or not hwnd:
        return 0, 0
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(int(hwnd), ctypes.byref(pt))
    return pt.x, pt.y


def make_overlay_window(hwnd):
    if not IS_WINDOWS or not hwnd:
        return
    hwnd = int(hwnd)
    ex = _get_long(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    _set_long(hwnd, GWL_EXSTYLE, ex)
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)


def place_overlay_window(hwnd, x, y, w, h):
    if not IS_WINDOWS or not hwnd:
        return
    user32.SetWindowPos(int(hwnd), HWND_TOPMOST, int(x), int(y), int(w), int(h), SWP_NOACTIVATE | SWP_NOOWNERZORDER)
    user32.ShowWindow(int(hwnd), SW_SHOWNOACTIVATE)


def hide_overlay_window(hwnd):
    if not IS_WINDOWS or not hwnd:
        return
    user32.ShowWindow(int(hwnd), SW_HIDE)


class GameStreamManager:
    def __init__(self, log_callback=None):
        self.hwnd = None
        self.viewer_hwnd = None
        self.is_streaming = False
        self.engaged = False
        self.log_cb = log_callback
        self.saved_game = None
        self.saved_viewer_ex = None
        self.applied_target = None
        self.pending_target = None
        self.pending_since = 0.0

    def log(self, text, tag="info"):
        if self.log_cb:
            self.log_cb(text, tag)

    def start_game_session(self, hwnd, win_title):
        self.hwnd = int(hwnd)
        self.is_streaming = True
        self.engaged = False
        self.saved_game = None
        self.applied_target = None
        self.pending_target = None

        if "minecraft" in win_title.lower():
            if disable_minecraft_auto_pause():
                self.log("Patched .minecraft/options.txt (pauseOnLostFocus=false). It applies on the next game launch.", "info")

        if IS_WINDOWS:
            try:
                user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, ctypes.c_void_p(0), SPIF_SENDCHANGE)
            except Exception:
                pass

    def stop_game_session(self):
        self.disengage()
        self.is_streaming = False
        self.hwnd = None

    def game_alive(self):
        return bool(IS_WINDOWS and self.hwnd and user32.IsWindow(self.hwnd))

    def foreground_hwnd(self):
        if not IS_WINDOWS:
            return 0
        return user32.GetForegroundWindow() or 0

    def game_has_focus(self):
        return self.game_alive() and self.foreground_hwnd() == self.hwnd

    def engage(self, viewer_hwnd, target):
        if not self.game_alive():
            return False

        self.viewer_hwnd = int(viewer_hwnd)
        if self.saved_viewer_ex is None:
            self.saved_viewer_ex = _get_long(self.viewer_hwnd, GWL_EXSTYLE)
        _set_long(self.viewer_hwnd, GWL_EXSTYLE, self.saved_viewer_ex | WS_EX_NOACTIVATE)

        self._save_game_state()
        self._make_game_borderless()
        self._move_game(target)
        self.engaged = True

        if not self.focus_game():
            self.log("Could not focus the game window automatically. Click the stream preview to take control.", "warn")
        return True

    def disengage(self):
        if not IS_WINDOWS:
            return

        if self.viewer_hwnd and self.saved_viewer_ex is not None and user32.IsWindow(self.viewer_hwnd):
            _set_long(self.viewer_hwnd, GWL_EXSTYLE, self.saved_viewer_ex)
        self.saved_viewer_ex = None

        if self.saved_game and self.game_alive():
            state = self.saved_game
            _set_long(self.hwnd, GWL_STYLE, state["style"])
            _set_long(self.hwnd, GWL_EXSTYLE, state["exstyle"])
            left, top, right, bottom = state["rect"]
            user32.SetWindowPos(
                self.hwnd, None, left, top, right - left, bottom - top,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )
        self.saved_game = None

        was_engaged = self.engaged
        self.engaged = False
        self.applied_target = None
        self.pending_target = None

        if was_engaged and self.viewer_hwnd and user32.IsWindow(self.viewer_hwnd):
            self._force_foreground(self.viewer_hwnd)
        self.viewer_hwnd = None

    def update_target(self, target):
        if not self.engaged or not self.game_alive():
            return

        if self.applied_target and self._same_rect(target, self.applied_target):
            self.pending_target = None
            return

        now = time.perf_counter()
        if self.pending_target is None or not self._same_rect(target, self.pending_target):
            self.pending_target = target
            self.pending_since = now
            return

        if now - self.pending_since >= 0.25:
            self._move_game(target)
            self.pending_target = None

    def focus_game(self):
        if not self.game_alive():
            return False
        return self._force_foreground(self.hwnd)

    @staticmethod
    def _same_rect(a, b, tol=2):
        return all(abs(int(p) - int(q)) <= tol for p, q in zip(a, b))

    def _save_game_state(self):
        if self.saved_game is not None:
            return
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        self.saved_game = {
            "style": _get_long(self.hwnd, GWL_STYLE),
            "exstyle": _get_long(self.hwnd, GWL_EXSTYLE),
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
        }

    def _make_game_borderless(self):
        if user32.IsIconic(self.hwnd) or user32.IsZoomed(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
            time.sleep(0.15)

        style = _get_long(self.hwnd, GWL_STYLE)
        exstyle = _get_long(self.hwnd, GWL_EXSTYLE)
        style &= ~(WS_CAPTION | WS_THICKFRAME)
        exstyle &= ~(WS_EX_DLGMODALFRAME | WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)
        _set_long(self.hwnd, GWL_STYLE, style)
        _set_long(self.hwnd, GWL_EXSTYLE, exstyle)
        user32.SetWindowPos(
            self.hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        )

    def _move_game(self, target):
        x, y, w, h = [int(v) for v in target]
        user32.SetWindowPos(
            self.hwnd, None, x, y, max(64, w), max(64, h),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER
        )
        self.applied_target = (x, y, w, h)

    def _force_foreground(self, hwnd):
        if not IS_WINDOWS or not hwnd or not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True

        current_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)

        attached = []
        for tid in {fg_tid, target_tid}:
            if tid and tid != current_tid and user32.AttachThreadInput(current_tid, tid, True):
                attached.append(tid)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(current_tid, tid, False)

        return user32.GetForegroundWindow() == hwnd
