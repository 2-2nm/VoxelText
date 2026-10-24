import os
import platform
import sys
import threading
import time
import multiprocessing
import json
import ctypes
from PIL import Image

try:
    ctypes.c_ulong.in_dll(ctypes.CDLL("nvapi64.dll"), "NvOptimusEnablement").value = 0x00000001
except Exception:
    pass
try:
    ctypes.c_int.in_dll(ctypes.CDLL("atiagd64.dll"), "AmdPowerXpressRequestHighPerformance").value = 1
except Exception:
    pass
try:
    import psutil
except ImportError:
    psutil = None
try:
    import pywinstyles
except ImportError:
    pywinstyles = None

from PySide6.QtCore import Qt, Signal, QObject, QTimer, Slot, QSize, QPoint
from PySide6.QtGui import (
    QFont, QIcon, QPixmap, QImage, QTextCursor, QTextCharFormat, QColor, QPalette
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QLineEdit, QCheckBox, QComboBox,
    QTextEdit, QScrollArea, QFileDialog, QMessageBox, QSplitter
)

from core.ascii import render_image_gpu, save_ascii_as_image, CHARSET_NAMES, get_charset, set_charset
from core.utils import MAX_WORKERS, get_resource_path, get_config_path
from video.player import GPUAsciiVideoPlayer
from video.audio import AudioPlayer
from game.player import GPUAsciiGamePlayer
from game.capture import list_active_windows, guess_game_window
from game.manager import GameStreamManager, client_origin
from ui.overlay import GameOverlayWindow, SegmentedButton


CONFIG_FILE = get_config_path()


class SignalBridge(QObject):
    log_signal = Signal(str, str, bool)
    video_frame_signal = Signal(object)
    video_time_signal = Signal(float, float)
    video_finished_signal = Signal()
    game_fps_signal = Signal(float)
    image_render_success_signal = Signal(object, str, str)
    image_render_error_signal = Signal(str)
    video_export_progress_signal = Signal(int, int, str)
    video_export_success_signal = Signal(str)
    video_export_error_signal = Signal(str)


class AsciiArtAppPySide6(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VoxelText")

        self.signals = SignalBridge()
        self.signals.log_signal.connect(self._on_log_signal)
        self.signals.video_frame_signal.connect(self._on_video_frame)
        self.signals.video_time_signal.connect(self.update_video_time_ui)
        self.signals.video_finished_signal.connect(self._on_video_finished)
        self.signals.game_fps_signal.connect(self._on_game_fps_update)
        self.signals.image_render_success_signal.connect(self._on_image_render_success)
        self.signals.image_render_error_signal.connect(self._on_image_render_error)
        self.signals.video_export_progress_signal.connect(self._on_video_export_progress)
        self.signals.video_export_success_signal.connect(self._on_video_export_success)
        self.signals.video_export_error_signal.connect(self._on_video_export_error)

        self.THEME_COLORS = {
            "Dark": {
                "bg_dark": "#08090C",
                "bg_surface": "#101217",
                "bg_panel": "#1C2028",
                "text_primary": "#E6E8EE",
                "text_muted": "#8B919E",
                "accent": "#D5DBE6",
                "cmd_prompt": "#8AA090",
                "title_tag": "#E6E8EE",
                "key_tag": "#8B919E",
                "val_tag": "#E6E8EE",
                "note_tag": "#C4A878",
                "log_info": "#8AA090",
                "log_warn": "#C4A878",
                "log_err": "#C47A7A",
            },
            "Light": {
                "bg_dark": "#ECE8E1",
                "bg_surface": "#F7F4EE",
                "bg_panel": "#E4DFD6",
                "text_primary": "#16161A",
                "text_muted": "#5C5A56",
                "accent": "#1C1E24",
                "cmd_prompt": "#2F6B4A",
                "title_tag": "#16161A",
                "key_tag": "#5C5A56",
                "val_tag": "#16161A",
                "note_tag": "#9A6700",
                "log_info": "#2F6B4A",
                "log_warn": "#9A6700",
                "log_err": "#B42318",
            },
        }

        self.cached_container_w = 800
        self.cached_container_h = 600

        self.settings = self.load_settings()
        set_charset(self.settings.get("ascii_charset", "Standard"))
        self.charset_combos = []
        self.current_theme = self.settings.get("theme", "Dark")
        self.colors = self.THEME_COLORS.get(self.current_theme, self.THEME_COLORS["Dark"])

        self.current_ascii_text = ""
        self.current_gui_preview = None
        self.current_pil_img = None
        self.last_converted_basename = ""
        self.preview_video_path = None
        self.preview_photo_img = None

        self.overdrive_mode_val = self.settings.get("photo_overdrive", False)
        self.video_overdrive_mode_val = self.settings.get("video_overdrive", False)

        self.is_video_playing = False
        self.is_video_paused = False
        self.is_game_playing = False
        self.active_game_player = None
        self._latest_game_img = None
        self._game_frame_inflight = False

        self.game_stream_mgr = GameStreamManager(log_callback=self.append_system_log)
        self.game_overlay = GameOverlayWindow()
        self.game_control_active = False
        self.game_control_timer = QTimer(self)
        self.game_control_timer.setInterval(100)
        self.game_control_timer.timeout.connect(self._game_control_tick)

        self.audio_player = AudioPlayer()
        self.active_video_player = None
        self.is_user_seeking = False
        self._is_last_log_progress = False

        self.selected_color_mode = self.settings.get("photo_color_mode", "Green")
        self.selected_video_color_mode = self.settings.get("video_color_mode", "Color")
        self.selected_game_color_mode = self.settings.get("game_color_mode", "Color")

        self.transparent_target_val = self.settings.get("photo_transparency", "white")
        self.video_transparent_target_val = self.settings.get("video_transparency", "black")
        self.game_transparent_target_val = self.settings.get("game_transparency", "black")

        self.color_buttons = {}
        self.video_color_buttons = {}
        self.game_color_buttons = {}

        self.resize(1500, 840)
        self.setMinimumSize(920, 620)
        self.center_window()
        self.is_fullscreen = False

        ip = get_resource_path("app-icon.ico")
        if os.path.exists(ip):
            self.setWindowIcon(QIcon(ip))

        self.setup_ui()
        self.apply_loaded_settings()
        self.show_fastfetch_placeholder()
        self.apply_title_bar_color()

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._refresh_current_view)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_splitter_initialized", False):
            self._splitter_initialized = True
            dh = max(140, self.settings.get("deck_height", 180))
            if hasattr(self, 'splitter'):
                QTimer.singleShot(0, lambda: self.splitter.setSizes([10000, dh]))

    def center_window(self):
        screen = QApplication.primaryScreen().geometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F11:
            self.toggle_fullscreen()
        elif key == Qt.Key_Escape:
            self.exit_fullscreen()
        elif key == Qt.Key_Up:
            self.scroll_text_v(-3)
        elif key == Qt.Key_Down:
            self.scroll_text_v(3)
        elif key == Qt.Key_Left:
            self.scroll_text_h(-3)
        elif key == Qt.Key_Right:
            self.scroll_text_h(3)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.on_closing()
        self.game_overlay.close()
        event.accept()

    def container_resize_event(self, event):
        w, h = event.size().width(), event.size().height()
        if w > 50 and h > 50:
            width_changed = abs(self.cached_container_w - w) > 5
            height_changed = abs(self.cached_container_h - h) > 5
            self.cached_container_w = w
            self.cached_container_h = h

            if (width_changed or height_changed) and hasattr(self, 'last_image_path') and self.last_image_path:
                self._resize_timer.start(100)

    def get_dynamic_preview_info(self):
        cw = max(100, self.cached_container_w - 32)
        ch = max(100, self.cached_container_h - 72)

        deck = self.seg_deck_mode.get()
        if deck == "Game":
            if self.chk_g_overdrive.isChecked():
                try:
                    cols = max(20, int(self.entry_g_overdrive.text().strip()))
                    return cols, cw, ch
                except ValueError:
                    pass
            cols = max(20, round(float(self.g_slider_width.value())))
            return cols, cw, ch

        if self.chk_v_overdrive.isChecked():
            try:
                cols = max(20, int(self.entry_v_overdrive.text().strip()))
                return cols, cw, ch
            except ValueError:
                pass

        cols = max(20, round(float(self.v_slider_width.value())))
        return cols, cw, ch

    def load_settings(self):
        defaults = {
            "theme": "Dark",
            "ascii_charset": "Standard",
            "deck_mode": "Image",
            "deck_height": 180,
            "photo_color_mode": "Green",
            "photo_fullcolor_style": "Blocky",
            "photo_width": 85,
            "photo_cutoff": 30,
            "photo_transparency": "white",
            "photo_overdrive": False,
            "photo_overdrive_val": "2000",
            "video_color_mode": "Color",
            "video_fullcolor_style": "Blocky",
            "video_width": 85,
            "video_transparency": "black",
            "video_overdrive": False,
            "video_overdrive_val": "2500",
            "game_color_mode": "Color",
            "game_fullcolor_style": "Blocky",
            "game_width": 100,
            "game_transparency": "black",
            "game_overdrive": False,
            "game_overdrive_val": "3000",
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    defaults.update(saved)
            except Exception:
                pass
        return defaults

    def save_settings(self):
        deck_h = self.settings.get("deck_height", 180)
        if hasattr(self, 'splitter') and self.bd.isVisible():
            sz = self.splitter.sizes()
            if len(sz) > 1 and sz[1] >= 110:
                deck_h = sz[1]

        game_title = self.combo_game_windows.currentText() if self.combo_game_windows.currentData() else self.settings.get("game_window_title", "")
        settings = {
            "game_window_title": game_title,
            "theme": self.current_theme,
            "ascii_charset": get_charset(),
            "deck_mode": self.seg_deck_mode.get(),
            "deck_height": max(140, deck_h),
            "photo_color_mode": self.selected_color_mode,
            "photo_fullcolor_style": self.seg_fullcolor_style.get(),
            "photo_width": round(self.slider_width.value()),
            "photo_cutoff": round(self.slider_thresh.value()),
            "photo_transparency": self.transparent_target_val,
            "photo_overdrive": self.chk_overdrive.isChecked(),
            "photo_overdrive_val": self.entry_overdrive.text().strip(),
            "video_color_mode": self.selected_video_color_mode,
            "video_fullcolor_style": self.seg_v_fullcolor_style.get(),
            "video_width": round(self.v_slider_width.value()),
            "video_transparency": self.video_transparent_target_val,
            "video_overdrive": self.chk_v_overdrive.isChecked(),
            "video_overdrive_val": self.entry_v_overdrive.text().strip(),
            "game_color_mode": self.selected_game_color_mode,
            "game_fullcolor_style": self.seg_g_fullcolor_style.get(),
            "game_width": round(self.g_slider_width.value()),
            "game_transparency": self.game_transparent_target_val,
            "game_overdrive": self.chk_g_overdrive.isChecked(),
            "game_overdrive_val": self.entry_g_overdrive.text().strip(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def get_color_options(self):
        is_light = self.current_theme == "Light"
        return [
            ("Green", "Green", "#2F6B4A" if is_light else "#8AA090"),
            ("Full Color", "Color", "#8A6A4A" if is_light else "#C8B8A4"),
            ("Monochrome", "White", "#1C1E24" if is_light else "#D5DBE6"),
            ("Red", "Red", "#FF3535" if is_light else "#FF0000"),
            ("Pink", "Pink", "#A33C4E" if is_light else "#C48A96"),
            ("Coral", "Coral", "#B42318" if is_light else "#C47A7A"),
            ("Amber", "Amber", "#9A6700" if is_light else "#C4A878"),
            ("Lime", "Lime", "#3B7A3A" if is_light else "#9AB888"),
            ("Cyan", "Cyan", "#1F6F86" if is_light else "#8EB4C4"),
            ("Violet", "Violet", "#5B4A8A" if is_light else "#A99AB8"),
            ("Blue", "Blue", "#1D4ED8" if is_light else "#8AA0C4"),
            ("Ember", "Orange", "#C2410C" if is_light else "#C49678"),
        ]

    def get_video_color_options(self):
        is_light = self.current_theme == "Light"
        return [
            ("Full Color", "Color", "#8A6A4A" if is_light else "#C8B8A4"),
            ("Monochrome", "White", "#1C1E24" if is_light else "#D5DBE6"),
        ]

    def update_icons(self):
        is_light = self.current_theme == "Light"

        path_clear = get_resource_path("clear_ascii_l.png" if is_light else "clear_ascii.png")
        if os.path.exists(path_clear):
            self.btn_clear_ascii.setIcon(QIcon(path_clear))
            self.btn_clear_ascii.setText("")
            self.btn_clear_ascii.setFixedSize(28, 20)
        else:
            self.btn_clear_ascii.setIcon(QIcon())
            self.btn_clear_ascii.setText("Clear")
            self.btn_clear_ascii.setFixedSize(50, 20)

        path_mute = get_resource_path("mute_l.png" if is_light else "mute.png")
        path_unmute = get_resource_path("unmute_l.png" if is_light else "unmute.png")

        self.icon_mute = QIcon(path_mute) if os.path.exists(path_mute) else QIcon()
        self.icon_unmute = QIcon(path_unmute) if os.path.exists(path_unmute) else QIcon()

        if self.audio_player.is_muted:
            if not self.icon_mute.isNull():
                self.btn_mute.setIcon(self.icon_mute)
                self.btn_mute.setText("")
                self.btn_mute.setFixedSize(28, 20)
            else:
                self.btn_mute.setIcon(QIcon())
                self.btn_mute.setText("Unmute")
                self.btn_mute.setFixedSize(50, 20)
        else:
            if not self.icon_unmute.isNull():
                self.btn_mute.setIcon(self.icon_unmute)
                self.btn_mute.setText("")
                self.btn_mute.setFixedSize(28, 20)
            else:
                self.btn_mute.setIcon(QIcon())
                self.btn_mute.setText("Mute")
                self.btn_mute.setFixedSize(50, 20)

    def apply_loaded_settings(self):
        self.switch_theme.setChecked(self.current_theme == "Dark")
        self.apply_theme_styles()

        deck = self.settings.get("deck_mode", "Image")
        if deck not in ["Image", "Video", "Game"]:
            deck = "Image"
        self.seg_deck_mode.set(deck)
        self.switch_deck_mode(deck)

        pw = self.settings.get("photo_width", 85)
        self.slider_width.setValue(pw)
        self.lbl_width.setText(f"{round(pw)} px")

        pc = self.settings.get("photo_cutoff", 30)
        self.slider_thresh.setValue(pc)
        self.lbl_thresh.setText(f"{round(pc)}%")

        pt = self.settings.get("photo_transparency", "white").capitalize()
        self.seg_alpha.set(pt)

        p_style = self.settings.get("photo_fullcolor_style", "Blocky")
        self.seg_fullcolor_style.set(p_style)

        self.entry_overdrive.setText(str(self.settings.get("photo_overdrive_val", "2000")))
        self.chk_overdrive.setChecked(self.overdrive_mode_val)
        self.toggle_overdrive()

        vw = self.settings.get("video_width", 85)
        self.v_slider_width.setValue(vw)
        self.lbl_v_width.setText(f"{round(vw)} px")

        vt = self.settings.get("video_transparency", "black").capitalize()
        self.seg_v_alpha.set(vt)

        v_style = self.settings.get("video_fullcolor_style", "Blocky")
        self.seg_v_fullcolor_style.set(v_style)

        self.entry_v_overdrive.setText(str(self.settings.get("video_overdrive_val", "2500")))
        self.chk_v_overdrive.setChecked(self.video_overdrive_mode_val)
        self.toggle_video_overdrive()

        gw = self.settings.get("game_width", 100)
        self.g_slider_width.setValue(gw)
        self.lbl_g_width.setText(f"{round(gw)} px")

        gt = self.settings.get("game_transparency", "black").capitalize()
        self.seg_g_alpha.set(gt)

        g_style = self.settings.get("game_fullcolor_style", "Blocky")
        self.seg_g_fullcolor_style.set(g_style)

        self.entry_g_overdrive.setText(str(self.settings.get("game_overdrive_val", "3000")))
        self.chk_g_overdrive.setChecked(self.settings.get("game_overdrive", False))
        self.toggle_game_overdrive()

        self.select_color_mode(self.selected_color_mode)
        self.select_video_color_mode(self.selected_video_color_mode)
        self.select_game_color_mode(self.selected_game_color_mode)

    def on_closing(self):
        self.save_settings()
        self.stop_video_playback()
        self.stop_game_stream()

    def clear_ascii_process(self):
        self.stop_video_playback()
        self.stop_game_stream()
        self.current_ascii_text = ""
        self.current_gui_preview = None
        self.current_pil_img = None
        self.last_converted_basename = ""
        self.preview_photo_img = None
        self.lbl_preview_img.clear()
        self.lbl_v_time.setText("00:00 / 00:00")
        self.v_slider_time.setValue(0)
        self.show_fastfetch_placeholder()
        self.append_system_log("ASCII preview cleared.", "info")

    def toggle_overdrive(self):
        if self.chk_overdrive.isChecked():
            self.lbl_width.hide()
            self.entry_overdrive.show()
            self.slider_width.setEnabled(False)
            self.append_system_log("Image Overdrive Width ENABLED", "warn")
        else:
            self.entry_overdrive.hide()
            self.lbl_width.show()
            self.slider_width.setEnabled(True)
            self.append_system_log("Image Overdrive Width DISABLED", "info")

    def toggle_video_overdrive(self):
        if self.chk_v_overdrive.isChecked():
            self.lbl_v_width.hide()
            self.entry_v_overdrive.show()
            self.v_slider_width.setEnabled(False)
            self.append_system_log("Video Overdrive Width ENABLED", "warn")
        else:
            self.entry_v_overdrive.hide()
            self.lbl_v_width.show()
            self.v_slider_width.setEnabled(True)
            self.append_system_log("Video Overdrive Width DISABLED", "info")

    def toggle_game_overdrive(self):
        if self.chk_g_overdrive.isChecked():
            self.lbl_g_width.hide()
            self.entry_g_overdrive.show()
            self.g_slider_width.setEnabled(False)
            self.append_system_log("Game Overdrive Width ENABLED", "warn")
        else:
            self.entry_g_overdrive.hide()
            self.lbl_g_width.show()
            self.g_slider_width.setEnabled(True)
            self.append_system_log("Game Overdrive Width DISABLED", "info")

    def apply_title_bar_color(self):
        if pywinstyles and platform.system() == "Windows":
            try:
                pywinstyles.change_header_color(self, color=self.colors["bg_dark"])
            except Exception:
                pass

    def get_sys_info(self):
        import datetime
        hn, un = platform.node() or "terminal", os.getlogin() if hasattr(os, "getlogin") else "root"
        oi, kr = f"{platform.system()} {platform.release()} ({platform.machine()})", platform.version().split(" ")[0]
        cpu = "Unknown CPU"
        try:
            if platform.system() == "Windows":
                import winreg
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
                winreg.CloseKey(k)
            else:
                cpu = platform.processor() or "Unknown CPU"
        except Exception:
            cpu = platform.processor() or "Unknown CPU"
        gpu = "Unknown GPU"
        try:
            if platform.system() == "Windows":
                import winreg
                k = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000",
                )
                gpu = winreg.QueryValueEx(k, "DriverDesc")[0].strip()
                winreg.CloseKey(k)
        except Exception:
            gpu = "Integrated / System Graphics"
        ram_str, disk_str, uptime_str = "N/A", "N/A", "N/A"
        if psutil:
            try:
                mem = psutil.virtual_memory()
                ram_str = f"{round(mem.used / (1024 ** 3), 1)} GB / {round(mem.total / (1024 ** 3), 1)} GB ({mem.percent}%)"
                dl = []
                for p in psutil.disk_partitions(all=False):
                    if os.name == "nt" and "cdrom" in p.opts.lower():
                        continue
                    try:
                        u = psutil.disk_usage(p.mountpoint)
                        dl.append(
                            f"{p.mountpoint.replace(chr(92), '')} {round(u.used / (1024 ** 3), 1)}/{round(u.total / (1024 ** 3), 1)} GB"
                        )
                    except PermissionError:
                        continue
                disk_str = " | ".join(dl)
                hrs, rem = divmod(int(time.time() - psutil.boot_time()), 3600)
                mins, _ = divmod(rem, 60)
                uptime_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
            except Exception:
                pass
        return {
            "title": f"{un}@{hn}",
            "OS": oi,
            "Kernel": kr,
            "Uptime": uptime_str,
            "DateTime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "CPU": cpu,
            "GPU": gpu,
            "Memory": ram_str,
            "Disk": disk_str,
            "Terminal": f"VXL Engine v3.0.0 Global ({MAX_WORKERS} Threads)",
        }

    def load_ascii_art_logo(self):
        tp = get_resource_path("ascii_terminal.txt")
        if os.path.exists(tp):
            try:
                with open(tp, "r", encoding="utf-8") as f:
                    lines = [l.rstrip("\r\n") for l in f.readlines()]
                    if lines:
                        return lines
            except Exception:
                pass
        return []

    def show_fastfetch_placeholder(self):
        us = os.getlogin() if hasattr(os, "getlogin") else "root"
        self.scroll_preview.hide()
        self.txt_ascii.show()

        info, ascii_logo = self.get_sys_info(), self.load_ascii_art_logo()
        self.txt_ascii.setReadOnly(False)
        self.txt_ascii.clear()

        def make_fmt(color, font_family="Consolas", size=9, bold=False, italic=False, bg=None):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFont(QFont(font_family, size, QFont.Bold if bold else QFont.Normal, italic))
            if bg:
                fmt.setBackground(QColor(bg))
            return fmt

        fmt_cmd = make_fmt(self.colors["cmd_prompt"], size=10, bold=True)
        fmt_ascii = make_fmt(self.colors["cmd_prompt"], size=9)
        fmt_title = make_fmt(self.colors["title_tag"], font_family="Georgia", size=16, italic=True)
        fmt_sep = make_fmt("#5C6370" if self.current_theme == "Dark" else "#7A776F")
        fmt_key = make_fmt(self.colors["key_tag"], size=9)
        fmt_val = make_fmt(self.colors["val_tag"], size=9)
        fmt_note = make_fmt(self.colors["note_tag"], size=9, italic=True)

        cursor = self.txt_ascii.textCursor()

        def append(text, fmt):
            cursor.insertText(text, fmt)

        specs = [
            ("OS", info["OS"]), ("Kernel", info["Kernel"]), ("Uptime", info["Uptime"]),
            ("Date Time", info["DateTime"]), ("CPU", info["CPU"]), ("GPU", info["GPU"]),
            ("Memory", info["Memory"]), ("Disk", info["Disk"]), ("Terminal", info["Terminal"]),
        ]

        append(f" ┌──({us}@vxl)-[~]\n └─$ afetch --system-diagnostics\n\n", fmt_cmd)
        maw = max(len(l) for l in ascii_logo) if ascii_logo else 0
        il = [("title", info["title"]), ("sep", "─" * (len(info["title"]) + 2))] + [("spec", s) for s in specs]
        tr = max(len(ascii_logo), len(il) + 2)

        for i in range(tr):
            if ascii_logo and maw > 0:
                ap = ascii_logo[i] if i < len(ascii_logo) else ""
                append(ap.ljust(maw) + (" " * 4), fmt_ascii)
            if i < len(il):
                tt, ct = il[i]
                if tt == "title":
                    append(ct + "\n", fmt_title)
                elif tt == "sep":
                    append(ct + "\n", fmt_sep)
                elif tt == "spec":
                    k, v = ct
                    append(f"{k:<10}: ", fmt_key)
                    append(f"{v}\n", fmt_val)
            elif i == len(il):
                append("Palette   : ", fmt_key)
                cols = (
                    ["#16161A", "#B42318", "#2F6B4A", "#9A6700", "#1D4ED8", "#5B4A8A", "#1F6F86", "#5C5A56"]
                    if self.current_theme == "Light"
                    else ["#08090C", "#C47A7A", "#8AA090", "#C4A878", "#8AA0C4", "#A99AB8", "#8EB4C4", "#D5DBE6"]
                )
                for c in cols:
                    append("██", make_fmt(c, bg=c))
                append("\n", fmt_val)
            else:
                append("\n", fmt_val)

        append("\n" + "─" * 90 + "\n", fmt_sep)
        append("           > Execute command to render local graphics into ASCII.            \n", fmt_note)
        append("─" * 90 + "\n", fmt_sep)

        self.txt_ascii.setReadOnly(True)

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.exit_fullscreen()
        else:
            self.is_fullscreen = True
            self.showFullScreen()

    def exit_fullscreen(self):
        if self.is_fullscreen:
            self.is_fullscreen = False
            self.showNormal()

    def toggle_theme_mode(self):
        self.current_theme = "Dark" if self.switch_theme.isChecked() else "Light"
        self.switch_theme.setText("DARK" if self.current_theme == "Dark" else "LIGHT")
        self.colors = self.THEME_COLORS[self.current_theme]
        self.apply_theme_styles()
        self.update_icons()

        for t, v, ch in self.get_color_options():
            if v in self.color_buttons:
                btn, _ = self.color_buttons[v]
                self.color_buttons[v] = (btn, ch)
        for t, v, ch in self.get_video_color_options():
            if v in self.video_color_buttons:
                btn, _ = self.video_color_buttons[v]
                self.video_color_buttons[v] = (btn, ch)
            if v in self.game_color_buttons:
                btn, _ = self.game_color_buttons[v]
                self.game_color_buttons[v] = (btn, ch)

        self.select_color_mode(self.selected_color_mode)
        self.select_video_color_mode(self.selected_video_color_mode)
        self.select_game_color_mode(self.selected_game_color_mode)

        if self.scroll_preview.isVisible() and hasattr(self, 'last_image_path') and self.last_image_path:
            if not self.is_video_playing and not self.is_game_playing:
                self.convert_image_process(skip_dialog=True)
        elif not self.is_video_playing and not self.is_game_playing:
            self.show_fastfetch_placeholder()

        self.apply_title_bar_color()
        self.append_system_log(f"Session theme switched to {self.current_theme}.", "info")

    def apply_theme_styles(self):
        c = self.colors
        bg_dark = c["bg_dark"]
        bg_surface = c["bg_surface"]
        bg_panel = c["bg_panel"]
        text_primary = c["text_primary"]
        text_muted = c["text_muted"]
        accent = c["accent"]

        btn_load_text = "#F7F4EE" if self.current_theme == "Light" else "#08090C"
        btn_load_bg = "#1C1E24" if self.current_theme == "Light" else "#D5DBE6"
        hover_bg = "#000000" if self.current_theme == "Light" else "#ffffff"
        hover_fg = "#ffffff" if self.current_theme == "Light" else "#000000"

        self.setStyleSheet(f"""
            QMainWindow, QWidget#centralWidget {{
                background-color: {bg_dark};
                color: {text_primary};
                font-family: Consolas, monospace;
            }}
            QFrame#surface {{
                background-color: {bg_surface};
                border: 1px solid {bg_panel};
                border-radius: 8px;
            }}
            QFrame#panel {{
                background-color: {bg_panel};
                border-radius: 6px;
            }}
            QLabel {{
                color: {text_primary};
                background-color: transparent;
            }}
            QLabel#badge {{
                background-color: {bg_panel};
                color: {text_primary};
                border-radius: 4px;
                padding: 1px 6px;
                font-weight: bold;
            }}
            QPushButton {{
                background-color: {bg_panel};
                color: {text_primary};
                border: none;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: {hover_fg};
            }}
            QPushButton:disabled {{
                color: {text_muted};
            }}
            QComboBox {{
                background-color: {bg_dark};
                color: {text_primary};
                border: 1px solid {bg_panel};
                border-radius: 4px;
                padding: 2px 6px;
            }}

            QSplitter::handle:vertical {{
                background-color: {bg_dark};
                height: 5px;
            }}
            QSplitter::handle:vertical:hover {{
                background-color: #8AA090;
            }}

            QSlider::groove:horizontal {{
                height: 6px;
                background: {bg_dark};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: #8AA090;
                border-radius: 3px;
            }}
            QSlider::add-page:horizontal {{
                background: {bg_dark};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {accent};
                width: 16px;
                height: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #8B919E;
            }}

            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {bg_panel};
                min-height: 20px;
                border-radius: 3px;
            }}

            QLineEdit {{
                background-color: {bg_dark};
                color: #C47A7A;
                border: 1px solid #C47A7A;
                border-radius: 4px;
                font-weight: bold;
            }}
            QCheckBox {{
                color: {text_primary};
                background-color: transparent;
            }}
            QTextEdit {{
                background-color: {bg_surface};
                color: {text_primary};
                border: none;
            }}
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
                border: none;
                background-color: transparent;
                background: transparent;
            }}
        """)

        self.btn_top_load.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_load_bg};
                color: {btn_load_text};
                font-weight: bold;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: #8B919E;
            }}
        """)

        self.btn_top_video.setStyleSheet("""
            QPushButton {
                background-color: #8AA090;
                color: #000000;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #6E8A74;
            }
        """)

        self.btn_top_game.setStyleSheet("""
            QPushButton {
                background-color: #C4A878;
                color: #08090C;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #A3895B;
            }
        """)

        self.seg_deck_mode.set_colors(
            selected_color=accent,
            unselected_color=bg_panel,
            text_selected=btn_load_text,
            text_unselected=text_primary
        )

        self.seg_alpha.set_colors(
            selected_color=accent,
            unselected_color=bg_panel,
            text_selected=btn_load_text,
            text_unselected=text_primary
        )

        self.seg_v_alpha.set_colors(
            selected_color="#8AA090",
            unselected_color=bg_panel,
            text_selected="#08090C",
            text_unselected=text_primary
        )

        self.seg_g_alpha.set_colors(
            selected_color="#C4A878",
            unselected_color=bg_panel,
            text_selected="#08090C",
            text_unselected=text_primary
        )

    def update_transparency_options(self, *args):
        is_color = (self.selected_color_mode == "Color")
        self.seg_alpha.setEnabled(not is_color)
        self.seg_fullcolor_style.setEnabled(is_color)

    def _on_photo_style_changed(self, val):
        if hasattr(self, 'last_image_path') and self.last_image_path and not self.is_video_playing:
            self.convert_image_process(skip_dialog=True)

    def _on_video_style_changed(self, val):
        self.append_system_log(f"Video style switched to {val}.", "info")

    def _make_charset_combo(self):
        combo = QComboBox()
        combo.setFixedHeight(22)
        combo.setToolTip("ASCII character set")
        combo.addItems(CHARSET_NAMES)
        combo.setCurrentText(get_charset())
        combo.currentTextChanged.connect(self._on_charset_changed)
        self.charset_combos.append(combo)
        return combo

    def _on_charset_changed(self, name):
        if not name or name == get_charset():
            return
        set_charset(name)
        for combo in self.charset_combos:
            if combo.currentText() != name:
                combo.blockSignals(True)
                combo.setCurrentText(name)
                combo.blockSignals(False)
        self.append_system_log(f"ASCII charset switched to {name}.", "info")
        if hasattr(self, 'last_image_path') and self.last_image_path and not self.is_video_playing and not self.is_game_playing:
            self.convert_image_process(skip_dialog=True)

    def _on_game_style_changed(self, val):
        self.append_system_log(f"Game ASCII style switched to {val}.", "info")

    def select_color_mode(self, value):
        self.selected_color_mode = value
        bg_panel = self.colors["bg_panel"]
        text_primary = self.colors["text_primary"]
        for val, (btn, ac) in self.color_buttons.items():
            if val == value:
                tc = "#08090C" if ac in ["#8AA090", "#D5DBE6", "#8EB4C4", "#C4A878"] else "#FFFFFF"
                btn.setStyleSheet(f"background-color: {ac}; color: {tc}; font-weight: bold; border-radius: 4px;")
            else:
                btn.setStyleSheet(f"background-color: {bg_panel}; color: {text_primary}; border-radius: 4px;")
        self.update_transparency_options()
        if hasattr(self, 'last_image_path') and self.last_image_path and not self.is_video_playing:
            self.convert_image_process(skip_dialog=True)

    def select_video_color_mode(self, value):
        self.selected_video_color_mode = value
        bg_panel = self.colors["bg_panel"]
        text_primary = self.colors["text_primary"]
        for val, (btn, ac) in self.video_color_buttons.items():
            if val == value:
                tc = "#08090C" if ac in ["#D5DBE6", "#C8B8A4"] else "#FFFFFF"
                btn.setStyleSheet(f"background-color: {ac}; color: {tc}; font-weight: bold; border-radius: 4px;")
            else:
                btn.setStyleSheet(f"background-color: {bg_panel}; color: {text_primary}; border-radius: 4px;")
        is_color = (value == "Color")
        self.seg_v_alpha.setEnabled(not is_color)
        self.seg_v_fullcolor_style.setEnabled(is_color)

    def select_game_color_mode(self, value):
        self.selected_game_color_mode = value
        bg_panel = self.colors["bg_panel"]
        text_primary = self.colors["text_primary"]
        for val, (btn, ac) in self.game_color_buttons.items():
            if val == value:
                tc = "#08090C" if ac in ["#D5DBE6", "#C8B8A4"] else "#FFFFFF"
                btn.setStyleSheet(f"background-color: {ac}; color: {tc}; font-weight: bold; border-radius: 4px;")
            else:
                btn.setStyleSheet(f"background-color: {bg_panel}; color: {text_primary}; border-radius: 4px;")
        is_color = (value == "Color")
        self.seg_g_alpha.setEnabled(not is_color)
        self.seg_g_fullcolor_style.setEnabled(is_color)

    def scroll_text_v(self, amount):
        if self.scroll_preview.isVisible():
            sb = self.scroll_preview.verticalScrollBar()
            sb.setValue(sb.value() + amount * 20)
        else:
            sb = self.txt_ascii.verticalScrollBar()
            sb.setValue(sb.value() + amount * 20)

    def scroll_text_h(self, amount):
        if self.scroll_preview.isVisible():
            sb = self.scroll_preview.horizontalScrollBar()
            sb.setValue(sb.value() + amount * 20)
        else:
            sb = self.txt_ascii.horizontalScrollBar()
            sb.setValue(sb.value() + amount * 20)

    def append_system_log(self, text, tag="info", is_progress=False):
        self.signals.log_signal.emit(text, tag, is_progress)

    @Slot(str, str, bool)
    def _on_log_signal(self, text, tag="info", is_progress=False):
        c = self.colors.get(f"log_{tag}", self.colors["log_info"])
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(c))
        cursor = self.txt_logs.textCursor()

        if is_progress:
            if self._is_last_log_progress:
                cursor.movePosition(QTextCursor.End)
                cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                cursor.insertText(f"[sys] {time.strftime('%H:%M:%S')}  {text}", fmt)
            else:
                cursor.movePosition(QTextCursor.End)
                cursor.insertText(f"[sys] {time.strftime('%H:%M:%S')}  {text}", fmt)
            self._is_last_log_progress = True
        else:
            cursor.movePosition(QTextCursor.End)
            if self._is_last_log_progress:
                cursor.insertText("\n")
            cursor.insertText(f"[sys] {time.strftime('%H:%M:%S')}  {text}\n", fmt)
            self._is_last_log_progress = False

        self.txt_logs.ensureCursorVisible()

    def switch_deck_mode(self, value):
        self.frame_photo_deck.hide()
        self.frame_video_deck.hide()
        self.frame_game_deck.hide()

        if value in ["Image", "Photo"]:
            self.frame_photo_deck.show()
            self.append_system_log("Settings deck switched to Image Settings.", "info")
        elif value == "Video":
            self.frame_video_deck.show()
            self.append_system_log("Settings deck switched to Video Settings.", "info")
        elif value == "Game":
            self.frame_game_deck.show()
            self.refresh_game_window_list()
            self.append_system_log("Settings deck switched to Game Stream Settings.", "info")

    def toggle_video_pause(self):
        if not self.is_video_playing:
            return
        self.is_video_paused = not self.is_video_paused
        if self.is_video_paused:
            self.btn_v_pause.setText("Resume")
            self.btn_v_pause.setStyleSheet("background-color: #C4A878; color: #08090C; font-weight: bold; border-radius: 4px;")
            self.audio_player.pause()
            self.append_system_log("Video playback paused.", "warn")
        else:
            btn_load_text = "#F7F4EE" if self.current_theme == "Light" else "#08090C"
            self.btn_v_pause.setText("Pause")
            self.btn_v_pause.setStyleSheet(f"background-color: {self.colors['accent']}; color: {btn_load_text}; font-weight: bold; border-radius: 4px;")
            self.audio_player.resume()
            self.append_system_log("Video playback resumed.", "info")

    def toggle_video_mute(self):
        is_muted = self.audio_player.toggle_mute()
        if is_muted:
            if not self.icon_mute.isNull():
                self.btn_mute.setIcon(self.icon_mute)
                self.btn_mute.setText("")
                self.btn_mute.setFixedSize(28, 20)
            else:
                self.btn_mute.setIcon(QIcon())
                self.btn_mute.setText("Unmute")
                self.btn_mute.setFixedSize(50, 20)
            self.append_system_log("Audio muted.", "warn")
        else:
            if not self.icon_unmute.isNull():
                self.btn_mute.setIcon(self.icon_unmute)
                self.btn_mute.setText("")
                self.btn_mute.setFixedSize(28, 20)
            else:
                self.btn_mute.setIcon(QIcon())
                self.btn_mute.setText("Mute")
                self.btn_mute.setFixedSize(50, 20)
            self.append_system_log("Audio unmuted.", "info")

    def stop_video_playback(self):
        if self.is_video_playing:
            btn_load_text = "#F7F4EE" if self.current_theme == "Light" else "#08090C"
            self.is_video_playing = False
            self.is_video_paused = False
            self.active_video_player = None
            self.audio_player.stop()

            self.btn_v_pause.setText("Pause")
            self.btn_v_pause.setStyleSheet(f"background-color: {self.colors['accent']}; color: {btn_load_text}; font-weight: bold; border-radius: 4px;")
            self.btn_v_pause.setEnabled(False)
            self.btn_v_stop.setEnabled(False)
            self.btn_top_video.setEnabled(True)

            self.lbl_v_time.setText("00:00 / 00:00")
            self.v_slider_time.setValue(0)
            self.append_system_log("Video playback stopped.", "warn")

    def _get_viewer_screen_rect(self):
        if not self.is_game_playing or self.isMinimized():
            return None
        pix = self.lbl_preview_img.pixmap()
        if not pix or pix.isNull() or not self.scroll_preview.isVisible():
            return None

        dpr = self.devicePixelRatioF()
        offset = self.lbl_preview_img.mapTo(self, QPoint(0, 0))
        pw, ph = pix.width(), pix.height()
        lw, lh = self.lbl_preview_img.width(), self.lbl_preview_img.height()
        dx = max(0, (lw - pw) // 2)
        dy = max(0, (lh - ph) // 2)

        ox, oy = client_origin(int(self.winId()))
        x = ox + int(round((offset.x() + dx) * dpr))
        y = oy + int(round((offset.y() + dy) * dpr))
        w = max(64, int(round(pw * dpr)))
        h = max(64, int(round(ph * dpr)))
        return (x, y, w, h)

    def engage_game_control(self, attempts=0):
        if not self.is_game_playing or self.game_control_active:
            return
        rect = self._get_viewer_screen_rect()
        if rect is None:
            if attempts < 40:
                QTimer.singleShot(150, lambda: self.engage_game_control(attempts + 1))
            else:
                self.append_system_log("Game control could not start: no stream frame was rendered.", "err")
            return

        if not self.game_stream_mgr.engage(int(self.winId()), rect):
            self.append_system_log("Game control could not start: game window is not available.", "err")
            return

        self.game_control_active = True
        self.game_overlay.set_frame(self.preview_photo_img)
        self.game_control_timer.start()
        self.append_system_log("Game control active. Keyboard and mouse go straight to the game through the stream view.", "info")
        self.append_system_log("Use the game in windowed mode (not exclusive fullscreen) for input to work.", "note")

    def disengage_game_control(self):
        self.game_control_timer.stop()
        self.game_overlay.hide_overlay()
        if self.game_control_active:
            self.game_control_active = False
            self.game_stream_mgr.disengage()

    def _game_control_tick(self):
        if not self.game_control_active:
            return
        if not self.is_game_playing or not self.game_stream_mgr.game_alive():
            if self.is_game_playing:
                self.append_system_log("Game window closed.", "warn")
            self.stop_game_stream()
            return

        rect = self._get_viewer_screen_rect()
        if rect is None:
            self.game_overlay.hide_overlay()
            return

        self.game_stream_mgr.update_target(rect)

        if self.game_stream_mgr.game_has_focus():
            self.game_overlay.show_at(rect)
        else:
            self.game_overlay.hide_overlay()

    def stop_game_stream(self):
        if self.is_game_playing or self.game_control_active:
            self.is_game_playing = False
            self.active_game_player = None
            self.disengage_game_control()
            self.game_stream_mgr.stop_game_session()
            self.btn_g_start.setEnabled(True)
            self.btn_g_stop.setEnabled(False)
            self.btn_top_game.setEnabled(True)
            self.lbl_g_fps.setText("0 FPS")
            self.append_system_log("Game ASCII Stream Stopped.", "warn")

    def refresh_game_window_list(self):
        previous_hwnd = self.combo_game_windows.currentData()
        previous_title = self.combo_game_windows.currentText()
        windows = list_active_windows()

        self.combo_game_windows.clear()
        if not windows:
            self.combo_game_windows.addItem("No active game window found", None)
            return

        for hwnd, title in windows:
            self.combo_game_windows.addItem(f"{title}", hwnd)

        idx = -1
        if previous_hwnd:
            idx = self.combo_game_windows.findData(previous_hwnd)
        if idx < 0 and previous_title:
            idx = self.combo_game_windows.findText(previous_title)
        if idx < 0:
            saved_title = self.settings.get("game_window_title", "")
            if saved_title:
                idx = self.combo_game_windows.findText(saved_title)
        if idx < 0:
            guessed = guess_game_window(windows)
            if guessed:
                idx = self.combo_game_windows.findData(guessed)
        if idx < 0:
            self.combo_game_windows.insertItem(0, "Select a game window...", None)
            idx = 0

        self.combo_game_windows.setCurrentIndex(idx)
        self.append_system_log(f"Detected {len(windows)} active window targets.", "info")

    def format_time(self, seconds):
        if seconds is None or seconds < 0:
            seconds = 0
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @Slot(float, float)
    def update_video_time_ui(self, current_sec, total_sec):
        if self.is_user_seeking:
            return
        if total_sec > 0:
            self.v_slider_time.setMaximum(int(total_sec))
            self.v_slider_time.setValue(min(int(current_sec), int(total_sec)))
        cur_str = self.format_time(current_sec)
        tot_str = self.format_time(total_sec)
        self.lbl_v_time.setText(f"{cur_str} / {tot_str}")

    @Slot(float)
    def _on_game_fps_update(self, fps):
        self.lbl_g_fps.setText(f"{round(fps)} FPS")

    def setup_ui(self):
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(6)

        tb = QFrame()
        tb.setObjectName("surface")
        tb.setFixedHeight(48)
        tb_layout = QHBoxLayout(tb)
        tb_layout.setContentsMargins(12, 6, 12, 6)

        lbl_title = QLabel("VoxelText")
        lbl_title.setFont(QFont("Georgia", 16, QFont.Normal, True))
        tb_layout.addWidget(lbl_title)

        lbl_sub = QLabel("- by 2.2nm")
        lbl_sub.setFont(QFont("Consolas", 11, QFont.Bold))
        lbl_sub.setStyleSheet(f"color: {self.colors['text_muted']};")
        tb_layout.addWidget(lbl_sub)

        tb_layout.addStretch()

        self.btn_top_game = QPushButton("Play Game")
        self.btn_top_game.setFixedSize(98, 32)
        self.btn_top_game.clicked.connect(self.start_game_stream_process)
        tb_layout.addWidget(self.btn_top_game)

        self.btn_top_video = QPushButton("Video")
        self.btn_top_video.setFixedSize(88, 32)
        self.btn_top_video.clicked.connect(self.convert_video_process)
        tb_layout.addWidget(self.btn_top_video)

        self.btn_top_load = QPushButton("Image")
        self.btn_top_load.setFixedSize(88, 32)
        self.btn_top_load.clicked.connect(self.convert_image_process)
        tb_layout.addWidget(self.btn_top_load)

        self.switch_theme = QCheckBox("DARK")
        self.switch_theme.setFont(QFont("Consolas", 9, QFont.Bold))
        self.switch_theme.setChecked(True)
        self.switch_theme.clicked.connect(self.toggle_theme_mode)
        tb_layout.addWidget(self.switch_theme)

        main_layout.addWidget(tb)

        self.ml = QWidget()
        ml_layout = QVBoxLayout(self.ml)
        ml_layout.setContentsMargins(0, 0, 0, 0)
        ml_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)

        self.pf_container = QFrame()
        self.pf_container.setObjectName("surface")
        pf_layout = QVBoxLayout(self.pf_container)
        pf_layout.setContentsMargins(4, 4, 4, 4)
        pf_layout.setSpacing(4)

        self.pf_container.resizeEvent = self.container_resize_event

        self.th_header = QFrame()
        self.th_header.setObjectName("panel")
        self.th_header.setFixedHeight(28)
        th_layout = QHBoxLayout(self.th_header)
        th_layout.setContentsMargins(8, 2, 8, 2)

        lbl_th = QLabel("TERMINAL OUTPUT PREVIEW")
        lbl_th.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_th.setStyleSheet(f"color: {self.colors['text_muted']};")
        th_layout.addWidget(lbl_th)

        th_layout.addStretch()

        for txt, cmd in [
            ("▲", lambda: self.scroll_text_v(-5)),
            ("▼", lambda: self.scroll_text_v(5)),
            ("◄", lambda: self.scroll_text_h(-5)),
            ("►", lambda: self.scroll_text_h(5)),
        ]:
            b = QPushButton(txt)
            b.setFixedSize(24, 20)
            b.clicked.connect(cmd)
            th_layout.addWidget(b)

        self.btn_toggle_deck = QPushButton("Hide Settings")
        self.btn_toggle_deck.setFixedHeight(20)
        self.btn_toggle_deck.setFont(QFont("Consolas", 8, QFont.Bold))
        self.btn_toggle_deck.clicked.connect(self.toggle_bottom_deck)
        th_layout.addWidget(self.btn_toggle_deck)

        self.btn_clear_ascii = QPushButton()
        self.btn_clear_ascii.clicked.connect(self.clear_ascii_process)
        th_layout.addWidget(self.btn_clear_ascii)

        self.btn_mute = QPushButton()
        self.btn_mute.clicked.connect(self.toggle_video_mute)
        th_layout.addWidget(self.btn_mute)

        self.update_icons()

        pf_layout.addWidget(self.th_header)

        self.txt_ascii = QTextEdit()
        self.txt_ascii.setObjectName("txt_ascii")
        self.txt_ascii.setFont(QFont("Consolas", 8))
        self.txt_ascii.setLineWrapMode(QTextEdit.NoWrap)
        pf_layout.addWidget(self.txt_ascii)

        self.scroll_preview = QScrollArea()
        self.scroll_preview.setWidgetResizable(True)
        self.scroll_preview_widget = QWidget()
        self.scroll_preview_layout = QVBoxLayout(self.scroll_preview_widget)
        self.scroll_preview_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_preview_img = QLabel()
        self.lbl_preview_img.setAlignment(Qt.AlignCenter)
        self.lbl_preview_img.mousePressEvent = self.on_preview_canvas_click
        self.scroll_preview_layout.addWidget(self.lbl_preview_img)
        self.scroll_preview.setWidget(self.scroll_preview_widget)
        pf_layout.addWidget(self.scroll_preview)
        self.scroll_preview.hide()

        self.splitter.addWidget(self.pf_container)

        self.bd = QFrame()
        self.bd.setObjectName("surface")
        self.bd.setMinimumHeight(140)
        bd_layout = QHBoxLayout(self.bd)
        bd_layout.setContentsMargins(10, 8, 10, 8)

        left_deck = QWidget()
        left_layout = QVBoxLayout(left_deck)
        left_layout.setContentsMargins(0, 0, 0, 0)

        deck_header = QWidget()
        dh_layout = QHBoxLayout(deck_header)
        dh_layout.setContentsMargins(0, 0, 0, 0)

        self.seg_deck_mode = SegmentedButton(
            ["Image", "Video", "Game"],
            default="Image",
            selected_color=self.colors["accent"],
            unselected_color=self.colors["bg_panel"]
        )
        self.seg_deck_mode.valueChanged.connect(self.switch_deck_mode)
        dh_layout.addWidget(self.seg_deck_mode)
        dh_layout.addStretch()

        left_layout.addWidget(deck_header)

        deck_content = QWidget()
        dc_layout = QHBoxLayout(deck_content)
        dc_layout.setContentsMargins(0, 0, 0, 0)

        self.frame_photo_deck = QWidget()
        fp_layout = QHBoxLayout(self.frame_photo_deck)
        fp_layout.setContentsMargins(0, 0, 0, 0)

        c1 = QWidget()
        c1.setFixedWidth(170)
        c1_layout = QVBoxLayout(c1)
        c1_layout.setContentsMargins(0, 0, 0, 0)
        lbl_p1 = QLabel("// PALETTE")
        lbl_p1.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_p1.setStyleSheet(f"color: {self.colors['text_muted']};")
        c1_layout.addWidget(lbl_p1)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("background: transparent; border: none;")
        sc.viewport().setStyleSheet("background: transparent;")
        sc_w = QWidget()
        sc_w.setStyleSheet("background: transparent;")
        sc_layout = QVBoxLayout(sc_w)
        sc_layout.setContentsMargins(0, 0, 4, 0)
        sc_layout.setSpacing(2)

        for t, v, ch in self.get_color_options():
            b = QPushButton(t)
            b.setFixedHeight(24)
            b.clicked.connect(lambda checked=False, val=v: self.select_color_mode(val))
            sc_layout.addWidget(b)
            self.color_buttons[v] = (b, ch)

        sc_layout.addStretch()
        sc.setWidget(sc_w)
        c1_layout.addWidget(sc)
        fp_layout.addWidget(c1)

        c2 = QWidget()
        c2_layout = QVBoxLayout(c2)
        c2_layout.setContentsMargins(0, 0, 0, 0)
        c2_layout.setSpacing(2)

        style_row = QWidget()
        style_layout = QHBoxLayout(style_row)
        style_layout.setContentsMargins(0, 0, 0, 0)

        self.seg_fullcolor_style = SegmentedButton(
            ["Blocky", "Pure ASCII"],
            default="Blocky",
            selected_color=self.colors["accent"],
            unselected_color=self.colors["bg_panel"]
        )
        self.seg_fullcolor_style.valueChanged.connect(self._on_photo_style_changed)
        style_layout.addWidget(self.seg_fullcolor_style)
        self.combo_charset_p = self._make_charset_combo()
        style_layout.addWidget(self.combo_charset_p)
        style_layout.addStretch()

        c2_layout.addWidget(style_row)

        lbl_p2 = QLabel("// PARAMETERS")
        lbl_p2.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_p2.setStyleSheet(f"color: {self.colors['text_muted']};")
        c2_layout.addWidget(lbl_p2)

        sf1 = QWidget()
        sf1_layout = QHBoxLayout(sf1)
        sf1_layout.setContentsMargins(0, 0, 0, 0)
        lbl_w = QLabel("Width")
        lbl_w.setFont(QFont("Consolas", 8))
        sf1_layout.addWidget(lbl_w)
        sf1_layout.addStretch()

        self.lbl_width = QLabel("85 px")
        self.lbl_width.setObjectName("badge")
        self.lbl_width.setFont(QFont("Consolas", 8, QFont.Bold))
        sf1_layout.addWidget(self.lbl_width)

        self.entry_overdrive = QLineEdit("2000")
        self.entry_overdrive.setFixedSize(55, 20)
        self.entry_overdrive.setAlignment(Qt.AlignCenter)
        self.entry_overdrive.hide()
        sf1_layout.addWidget(self.entry_overdrive)

        self.chk_overdrive = QCheckBox("Overdrive")
        self.chk_overdrive.setFont(QFont("Consolas", 8, QFont.Bold))
        self.chk_overdrive.setStyleSheet("color: #C47A7A;")
        self.chk_overdrive.clicked.connect(self.toggle_overdrive)
        sf1_layout.addWidget(self.chk_overdrive)

        c2_layout.addWidget(sf1)

        self.slider_width = QSlider(Qt.Horizontal)
        self.slider_width.setRange(30, 200)
        self.slider_width.setValue(85)
        self.slider_width.valueChanged.connect(lambda v: self.lbl_width.setText(f"{v} px"))
        c2_layout.addWidget(self.slider_width)

        sf2 = QWidget()
        sf2_layout = QHBoxLayout(sf2)
        sf2_layout.setContentsMargins(0, 0, 0, 0)
        lbl_c = QLabel("Cutoff")
        lbl_c.setFont(QFont("Consolas", 8))
        sf2_layout.addWidget(lbl_c)
        sf2_layout.addStretch()

        self.lbl_thresh = QLabel("30%")
        self.lbl_thresh.setObjectName("badge")
        self.lbl_thresh.setFont(QFont("Consolas", 8, QFont.Bold))
        sf2_layout.addWidget(self.lbl_thresh)

        c2_layout.addWidget(sf2)

        self.slider_thresh = QSlider(Qt.Horizontal)
        self.slider_thresh.setRange(0, 100)
        self.slider_thresh.setValue(30)
        self.slider_thresh.valueChanged.connect(lambda v: self.lbl_thresh.setText(f"{v}%"))
        c2_layout.addWidget(self.slider_thresh)

        af = QWidget()
        af_layout = QHBoxLayout(af)
        af_layout.setContentsMargins(0, 0, 0, 0)
        lbl_tr = QLabel("Transparency")
        lbl_tr.setFont(QFont("Consolas", 8))
        af_layout.addWidget(lbl_tr)
        af_layout.addStretch()

        self.seg_alpha = SegmentedButton(
            ["Black", "White"],
            default="White",
            selected_color=self.colors["accent"],
            unselected_color=self.colors["bg_panel"]
        )
        self.seg_alpha.valueChanged.connect(self._on_photo_transparency_changed)
        af_layout.addWidget(self.seg_alpha)

        c2_layout.addWidget(af)

        self.btn_save_photo = QPushButton("Save as PNG")
        self.btn_save_photo.setFont(QFont("Consolas", 9, QFont.Bold))
        self.btn_save_photo.setFixedHeight(24)
        self.btn_save_photo.clicked.connect(self.save_as_photo_process)
        c2_layout.addWidget(self.btn_save_photo)

        fp_layout.addWidget(c2)
        dc_layout.addWidget(self.frame_photo_deck)

        self.frame_video_deck = QWidget()
        fv_layout = QHBoxLayout(self.frame_video_deck)
        fv_layout.setContentsMargins(0, 0, 0, 0)

        v_c1 = QWidget()
        v_c1.setFixedWidth(170)
        v_c1_layout = QVBoxLayout(v_c1)
        v_c1_layout.setContentsMargins(0, 0, 0, 0)
        lbl_vp1 = QLabel("// PALETTE")
        lbl_vp1.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_vp1.setStyleSheet(f"color: {self.colors['text_muted']};")
        v_c1_layout.addWidget(lbl_vp1)

        v_sc = QScrollArea()
        v_sc.setWidgetResizable(True)
        v_sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v_sc.setStyleSheet("background: transparent; border: none;")
        v_sc.viewport().setStyleSheet("background: transparent;")
        v_sc_w = QWidget()
        v_sc_w.setStyleSheet("background: transparent;")
        v_sc_layout = QVBoxLayout(v_sc_w)
        v_sc_layout.setContentsMargins(0, 0, 4, 0)
        v_sc_layout.setSpacing(2)

        for t, v, ch in self.get_video_color_options():
            b = QPushButton(t)
            b.setFixedHeight(24)
            b.clicked.connect(lambda checked=False, val=v: self.select_video_color_mode(val))
            v_sc_layout.addWidget(b)
            self.video_color_buttons[v] = (b, ch)

        v_sc_layout.addStretch()
        v_sc.setWidget(v_sc_w)
        v_c1_layout.addWidget(v_sc)
        fv_layout.addWidget(v_c1)

        v_c2 = QWidget()
        v_c2_layout = QVBoxLayout(v_c2)
        v_c2_layout.setContentsMargins(0, 0, 0, 0)
        v_c2_layout.setSpacing(2)

        v_style_row = QWidget()
        v_style_layout = QHBoxLayout(v_style_row)
        v_style_layout.setContentsMargins(0, 0, 0, 0)

        self.seg_v_fullcolor_style = SegmentedButton(
            ["Blocky", "Pure ASCII"],
            default="Blocky",
            selected_color="#8AA090",
            unselected_color=self.colors["bg_panel"],
            text_selected="#08090C"
        )
        self.seg_v_fullcolor_style.valueChanged.connect(self._on_video_style_changed)
        v_style_layout.addWidget(self.seg_v_fullcolor_style)
        self.combo_charset_v = self._make_charset_combo()
        v_style_layout.addWidget(self.combo_charset_v)
        v_style_layout.addStretch()

        v_c2_layout.addWidget(v_style_row)

        v_param_header = QWidget()
        v_ph_layout = QHBoxLayout(v_param_header)
        v_ph_layout.setContentsMargins(0, 0, 0, 0)

        lbl_vp2 = QLabel("// PARAMETERS")
        lbl_vp2.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_vp2.setStyleSheet(f"color: {self.colors['text_muted']};")
        v_ph_layout.addWidget(lbl_vp2)
        v_ph_layout.addStretch()

        self.btn_save_video = QPushButton("Save as MP4")
        self.btn_save_video.setFont(QFont("Consolas", 8, QFont.Bold))
        self.btn_save_video.setFixedHeight(20)
        self.btn_save_video.clicked.connect(self.save_as_video_process)
        v_ph_layout.addWidget(self.btn_save_video)

        v_c2_layout.addWidget(v_param_header)

        vsf1 = QWidget()
        vsf1_layout = QHBoxLayout(vsf1)
        vsf1_layout.setContentsMargins(0, 0, 0, 0)
        lbl_vw = QLabel("Width")
        lbl_vw.setFont(QFont("Consolas", 8))
        vsf1_layout.addWidget(lbl_vw)
        vsf1_layout.addStretch()

        self.lbl_v_width = QLabel("85 px")
        self.lbl_v_width.setObjectName("badge")
        self.lbl_v_width.setFont(QFont("Consolas", 8, QFont.Bold))
        vsf1_layout.addWidget(self.lbl_v_width)

        self.entry_v_overdrive = QLineEdit("2500")
        self.entry_v_overdrive.setFixedSize(55, 20)
        self.entry_v_overdrive.setAlignment(Qt.AlignCenter)
        self.entry_v_overdrive.hide()
        vsf1_layout.addWidget(self.entry_v_overdrive)

        self.chk_v_overdrive = QCheckBox("Overdrive")
        self.chk_v_overdrive.setFont(QFont("Consolas", 8, QFont.Bold))
        self.chk_v_overdrive.setStyleSheet("color: #C47A7A;")
        self.chk_v_overdrive.clicked.connect(self.toggle_video_overdrive)
        vsf1_layout.addWidget(self.chk_v_overdrive)

        v_c2_layout.addWidget(vsf1)

        self.v_slider_width = QSlider(Qt.Horizontal)
        self.v_slider_width.setRange(30, 500)
        self.v_slider_width.setValue(85)
        self.v_slider_width.valueChanged.connect(lambda v: self.lbl_v_width.setText(f"{v} px"))
        v_c2_layout.addWidget(self.v_slider_width)

        vtf = QWidget()
        vtf_layout = QHBoxLayout(vtf)
        vtf_layout.setContentsMargins(0, 0, 0, 0)
        lbl_tm = QLabel("Timeline")
        lbl_tm.setFont(QFont("Consolas", 8))
        vtf_layout.addWidget(lbl_tm)
        vtf_layout.addStretch()

        self.lbl_v_time = QLabel("00:00 / 00:00")
        self.lbl_v_time.setObjectName("badge")
        self.lbl_v_time.setFont(QFont("Consolas", 8, QFont.Bold))
        vtf_layout.addWidget(self.lbl_v_time)

        v_c2_layout.addWidget(vtf)

        self.v_slider_time = QSlider(Qt.Horizontal)
        self.v_slider_time.setRange(0, 1000)
        self.v_slider_time.setValue(0)
        self.v_slider_time.sliderPressed.connect(lambda: setattr(self, "is_user_seeking", True))
        self.v_slider_time.sliderReleased.connect(self._on_seek_end)
        v_c2_layout.addWidget(self.v_slider_time)

        vaf = QWidget()
        vaf_layout = QHBoxLayout(vaf)
        vaf_layout.setContentsMargins(0, 0, 0, 0)
        lbl_vtr = QLabel("Transparency")
        lbl_vtr.setFont(QFont("Consolas", 8))
        vaf_layout.addWidget(lbl_vtr)
        vaf_layout.addStretch()

        self.seg_v_alpha = SegmentedButton(
            ["Black", "White"],
            default="Black",
            selected_color="#8AA090",
            unselected_color=self.colors["bg_panel"],
            text_selected="#08090C"
        )
        self.seg_v_alpha.valueChanged.connect(self._on_video_transparency_changed)
        vaf_layout.addWidget(self.seg_v_alpha)

        v_c2_layout.addWidget(vaf)

        ctrl_frame = QWidget()
        ctrl_layout = QHBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_v_pause = QPushButton("Pause")
        self.btn_v_pause.setFont(QFont("Consolas", 8, QFont.Bold))
        self.btn_v_pause.setEnabled(False)
        self.btn_v_pause.clicked.connect(self.toggle_video_pause)
        ctrl_layout.addWidget(self.btn_v_pause)

        self.btn_v_stop = QPushButton("Stop")
        self.btn_v_stop.setFont(QFont("Consolas", 8, QFont.Bold))
        self.btn_v_stop.setStyleSheet("background-color: #C47A7A; color: #FFFFFF; font-weight: bold; border-radius: 4px;")
        self.btn_v_stop.setEnabled(False)
        self.btn_v_stop.clicked.connect(self.stop_video_playback)
        ctrl_layout.addWidget(self.btn_v_stop)

        v_c2_layout.addWidget(ctrl_frame)

        fv_layout.addWidget(v_c2)
        dc_layout.addWidget(self.frame_video_deck)
        self.frame_video_deck.hide()

        self.frame_game_deck = QWidget()
        fg_layout = QHBoxLayout(self.frame_game_deck)
        fg_layout.setContentsMargins(0, 0, 0, 0)

        g_c1 = QWidget()
        g_c1.setFixedWidth(170)
        g_c1_layout = QVBoxLayout(g_c1)
        g_c1_layout.setContentsMargins(0, 0, 0, 0)
        lbl_gp1 = QLabel("// PALETTE")
        lbl_gp1.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_gp1.setStyleSheet(f"color: {self.colors['text_muted']};")
        g_c1_layout.addWidget(lbl_gp1)

        g_sc = QScrollArea()
        g_sc.setWidgetResizable(True)
        g_sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        g_sc.setStyleSheet("background: transparent; border: none;")
        g_sc.viewport().setStyleSheet("background: transparent;")
        g_sc_w = QWidget()
        g_sc_w.setStyleSheet("background: transparent;")
        g_sc_layout = QVBoxLayout(g_sc_w)
        g_sc_layout.setContentsMargins(0, 0, 4, 0)
        g_sc_layout.setSpacing(2)

        for t, v, ch in self.get_video_color_options():
            b = QPushButton(t)
            b.setFixedHeight(24)
            b.clicked.connect(lambda checked=False, val=v: self.select_game_color_mode(val))
            g_sc_layout.addWidget(b)
            self.game_color_buttons[v] = (b, ch)

        g_sc_layout.addStretch()
        g_sc.setWidget(g_sc_w)
        g_c1_layout.addWidget(g_sc)
        fg_layout.addWidget(g_c1)

        g_c2 = QWidget()
        g_c2_layout = QVBoxLayout(g_c2)
        g_c2_layout.setContentsMargins(0, 0, 0, 0)
        g_c2_layout.setSpacing(2)

        g_style_row = QWidget()
        g_style_layout = QHBoxLayout(g_style_row)
        g_style_layout.setContentsMargins(0, 0, 0, 0)

        self.seg_g_fullcolor_style = SegmentedButton(
            ["Blocky", "Pure ASCII"],
            default="Blocky",
            selected_color="#C4A878",
            unselected_color=self.colors["bg_panel"],
            text_selected="#08090C"
        )
        self.seg_g_fullcolor_style.valueChanged.connect(self._on_game_style_changed)
        g_style_layout.addWidget(self.seg_g_fullcolor_style)
        self.combo_charset_g = self._make_charset_combo()
        g_style_layout.addWidget(self.combo_charset_g)
        g_style_layout.addStretch()

        g_c2_layout.addWidget(g_style_row)

        lbl_gp2 = QLabel("// TARGET WINDOW & PARAMETERS")
        lbl_gp2.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_gp2.setStyleSheet(f"color: {self.colors['text_muted']};")
        g_c2_layout.addWidget(lbl_gp2)

        gw_row = QWidget()
        gw_layout = QHBoxLayout(gw_row)
        gw_layout.setContentsMargins(0, 0, 0, 0)

        self.combo_game_windows = QComboBox()
        self.combo_game_windows.setFixedHeight(22)
        gw_layout.addWidget(self.combo_game_windows, stretch=1)

        btn_ref_win = QPushButton("Refresh")
        btn_ref_win.setFixedHeight(22)
        btn_ref_win.clicked.connect(self.refresh_game_window_list)
        gw_layout.addWidget(btn_ref_win)

        g_c2_layout.addWidget(gw_row)

        gsf1 = QWidget()
        gsf1_layout = QHBoxLayout(gsf1)
        gsf1_layout.setContentsMargins(0, 0, 0, 0)
        lbl_gw = QLabel("Width")
        lbl_gw.setFont(QFont("Consolas", 8))
        gsf1_layout.addWidget(lbl_gw)
        gsf1_layout.addStretch()

        self.lbl_g_width = QLabel("100 px")
        self.lbl_g_width.setObjectName("badge")
        self.lbl_g_width.setFont(QFont("Consolas", 8, QFont.Bold))
        gsf1_layout.addWidget(self.lbl_g_width)

        self.entry_g_overdrive = QLineEdit("3000")
        self.entry_g_overdrive.setFixedSize(55, 20)
        self.entry_g_overdrive.setAlignment(Qt.AlignCenter)
        self.entry_g_overdrive.hide()
        gsf1_layout.addWidget(self.entry_g_overdrive)

        self.chk_g_overdrive = QCheckBox("Overdrive")
        self.chk_g_overdrive.setFont(QFont("Consolas", 8, QFont.Bold))
        self.chk_g_overdrive.setStyleSheet("color: #C47A7A;")
        self.chk_g_overdrive.clicked.connect(self.toggle_game_overdrive)
        gsf1_layout.addWidget(self.chk_g_overdrive)

        g_c2_layout.addWidget(gsf1)

        self.g_slider_width = QSlider(Qt.Horizontal)
        self.g_slider_width.setRange(30, 500)
        self.g_slider_width.setValue(100)
        self.g_slider_width.valueChanged.connect(lambda v: self.lbl_g_width.setText(f"{v} px"))
        g_c2_layout.addWidget(self.g_slider_width)

        gaf = QWidget()
        gaf_layout = QHBoxLayout(gaf)
        gaf_layout.setContentsMargins(0, 0, 0, 0)
        lbl_gtr = QLabel("Transparency")
        lbl_gtr.setFont(QFont("Consolas", 8))
        gaf_layout.addWidget(lbl_gtr)
        gaf_layout.addStretch()

        self.lbl_g_fps = QLabel("0 FPS")
        self.lbl_g_fps.setObjectName("badge")
        self.lbl_g_fps.setFont(QFont("Consolas", 8, QFont.Bold))
        gaf_layout.addWidget(self.lbl_g_fps)

        self.seg_g_alpha = SegmentedButton(
            ["Black", "White"],
            default="Black",
            selected_color="#C4A878",
            unselected_color=self.colors["bg_panel"],
            text_selected="#08090C"
        )
        self.seg_g_alpha.valueChanged.connect(self._on_game_transparency_changed)
        gaf_layout.addWidget(self.seg_g_alpha)

        g_c2_layout.addWidget(gaf)

        g_ctrl_frame = QWidget()
        g_ctrl_layout = QHBoxLayout(g_ctrl_frame)
        g_ctrl_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_g_start = QPushButton("Start Stream")
        self.btn_g_start.setFont(QFont("Consolas", 8, QFont.Bold))
        self.btn_g_start.setStyleSheet("background-color: #C4A878; color: #08090C; font-weight: bold; border-radius: 4px;")
        self.btn_g_start.clicked.connect(self.start_game_stream_process)
        g_ctrl_layout.addWidget(self.btn_g_start)

        self.btn_g_stop = QPushButton("Stop Stream")
        self.btn_g_stop.setFont(QFont("Consolas", 8, QFont.Bold))
        self.btn_g_stop.setStyleSheet("background-color: #C47A7A; color: #FFFFFF; font-weight: bold; border-radius: 4px;")
        self.btn_g_stop.setEnabled(False)
        self.btn_g_stop.clicked.connect(self.stop_game_stream)
        g_ctrl_layout.addWidget(self.btn_g_stop)

        g_c2_layout.addWidget(g_ctrl_frame)

        fg_layout.addWidget(g_c2)
        dc_layout.addWidget(self.frame_game_deck)
        self.frame_game_deck.hide()

        left_layout.addWidget(deck_content)
        bd_layout.addWidget(left_deck, stretch=2)

        c3 = QWidget()
        c3_layout = QVBoxLayout(c3)
        c3_layout.setContentsMargins(0, 0, 0, 0)

        c3_header = QWidget()
        c3h_layout = QHBoxLayout(c3_header)
        c3h_layout.setContentsMargins(0, 0, 0, 0)

        lbl_log = QLabel("// CONSOLE LOGS")
        lbl_log.setFont(QFont("Consolas", 8, QFont.Bold))
        lbl_log.setStyleSheet(f"color: {self.colors['text_muted']};")
        c3h_layout.addWidget(lbl_log)
        c3h_layout.addStretch()

        btn_close_deck = QPushButton("×")
        btn_close_deck.setObjectName("btnCloseDeck")
        btn_close_deck.setFixedSize(20, 20)
        btn_close_deck.setFont(QFont("Consolas", 10, QFont.Bold))
        btn_close_deck.clicked.connect(self.hide_bottom_deck)
        c3h_layout.addWidget(btn_close_deck)

        c3_layout.addWidget(c3_header)

        self.txt_logs = QTextEdit()
        self.txt_logs.setObjectName("txt_logs")
        self.txt_logs.setFont(QFont("Consolas", 8))
        self.txt_logs.setReadOnly(True)
        c3_layout.addWidget(self.txt_logs)

        bd_layout.addWidget(c3, stretch=1)

        self.splitter.addWidget(self.bd)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        ml_layout.addWidget(self.splitter)
        main_layout.addWidget(self.ml)

        self.append_system_log(f"Engine initialized. Multi-Core Active ({MAX_WORKERS} Threads).", "info")

    def _on_photo_transparency_changed(self, val):
        self.transparent_target_val = val.lower()
        if hasattr(self, 'last_image_path') and self.last_image_path and not self.is_video_playing:
            self.convert_image_process(skip_dialog=True)

    def _on_video_transparency_changed(self, val):
        self.video_transparent_target_val = val.lower()

    def _on_game_transparency_changed(self, val):
        self.game_transparent_target_val = val.lower()

    def _on_seek_end(self):
        if self.active_video_player:
            self.active_video_player.seek(self.v_slider_time.value())
        self.is_user_seeking = False

    def toggle_bottom_deck(self):
        if self.bd.isVisible():
            self.bd.hide()
            self.btn_toggle_deck.setText("Show Settings")
            self.append_system_log("Settings deck hidden.", "info")
        else:
            self.bd.show()
            dh = max(140, self.settings.get("deck_height", 180))
            self.splitter.setSizes([10000, dh])
            self.btn_toggle_deck.setText("Hide Settings")
            self.append_system_log("Settings deck displayed.", "info")

        QTimer.singleShot(50, self._refresh_current_view)

    def _refresh_current_view(self):
        if hasattr(self, 'last_image_path') and self.last_image_path and not self.is_video_playing and not self.is_game_playing:
            self.convert_image_process(skip_dialog=True)

    def hide_bottom_deck(self):
        if self.bd.isVisible():
            self.bd.hide()
            self.btn_toggle_deck.setText("Show Settings")
            self.append_system_log("Settings deck closed.", "info")

    def save_as_photo_process(self):
        if not self.current_ascii_text and not getattr(self, "current_pil_img", None):
            self.append_system_log("Save PNG cancelled: No ASCII data present.", "warn")
            return

        dpn = f"{self.last_converted_basename}_ascii.png" if self.last_converted_basename else "ascii_photo.png"
        sp, _ = QFileDialog.getSaveFileName(
            self,
            "Save ASCII as PNG...",
            dpn,
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;All Files (*.*)",
        )

        if not sp:
            self.append_system_log("Save PNG cancelled by user.", "warn")
            return

        m = self.selected_color_mode
        p_style = self.seg_fullcolor_style.get()
        cmap = (
            {
                "Green": "#2F6B4A", "Cyan": "#1F6F86", "Pink": "#A33C4E",
                "Coral": "#B42318", "Amber": "#9A6700", "Lime": "#3B7A3A",
                "Violet": "#5B4A8A", "Blue": "#1D4ED8", "Orange": "#C2410C",
                "White": "#1C1E24", "Red": "#FF2D2D",
            }
            if self.current_theme == "Light"
            else {
                "Green": "#8AA090", "Pink": "#C48A96", "Red": "#FF0000",
                "Coral": "#C47A7A", "Amber": "#C4A878", "Lime": "#9AB888", "Cyan": "#8EB4C4",
                "Violet": "#A99AB8", "Blue": "#8AA0C4", "Orange": "#C49678",
                "White": "#D5DBE6",
            }
        )

        try:
            if m == "Color" and hasattr(self, 'last_image_path') and self.last_image_path:
                tw = int(self.entry_overdrive.text().strip()) if self.chk_overdrive.isChecked() else round(float(self.slider_width.value()))
                high_res_img, _ = render_image_gpu(
                    image_path=self.last_image_path,
                    target_cols=tw,
                    max_ui_w=3840,
                    max_ui_h=2160,
                    color_mode="Color",
                    fullcolor_style=p_style,
                    palette_hex="#8AA090",
                    transparent_target=self.transparent_target_val,
                    theme_bg_color=self.colors["bg_surface"]
                )
                
                min_target_width = 2560
                if high_res_img.width < min_target_width and high_res_img.width > 0:
                    scale = min_target_width / high_res_img.width
                    new_w = int(high_res_img.width * scale)
                    new_h = int(high_res_img.height * scale)
                    high_res_img = high_res_img.resize((new_w, new_h), Image.Resampling.NEAREST)

                high_res_img.save(sp)
            else:
                save_ascii_as_image(
                    ascii_content=self.current_ascii_text,
                    output_path=sp,
                    bg_color=self.colors["bg_surface"],
                    text_color=cmap.get(m, "#8AA090"),
                    gui_preview_data=self.current_gui_preview if m == "Color" else None,
                )
                
                if os.path.exists(sp):
                    saved_img = Image.open(sp)
                    if saved_img.width < 2560 and saved_img.width > 0:
                        scale = 2560 / saved_img.width
                        new_w = int(saved_img.width * scale)
                        new_h = int(saved_img.height * scale)
                        upscaled = saved_img.resize((new_w, new_h), Image.Resampling.NEAREST)
                        upscaled.save(sp)

            self.append_system_log(f"High-res photo exported to: {os.path.basename(sp)}", "info")
        except Exception as e:
            self.append_system_log(f"Save PNG error: {e}", "err")
            QMessageBox.critical(self, "Error", f"Failed:\n{e}")

    def save_as_video_process(self):
        self.stop_video_playback()

        fp = getattr(self, "preview_video_path", None)
        if not fp or not os.path.exists(fp):
            fp, _ = QFileDialog.getOpenFileName(
                self,
                "Select Source Video for Export",
                "",
                "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*.*)",
            )
            if not fp:
                self.append_system_log("Video export cancelled: No source video selected.", "warn")
                return

        dpn = f"{os.path.splitext(os.path.basename(fp))[0]}_ascii.mp4"
        sp, _ = QFileDialog.getSaveFileName(
            self,
            "Save ASCII Video as MP4...",
            dpn,
            "MP4 Video (*.mp4);;All Files (*.*)",
        )
        if not sp:
            self.append_system_log("Video export cancelled by user.", "warn")
            return

        if self.chk_v_overdrive.isChecked():
            try:
                tw = int(self.entry_v_overdrive.text().strip())
                if tw <= 0:
                    raise ValueError
            except ValueError:
                self.append_system_log("Invalid Video Overdrive value! Reverting to slider width.", "err")
                tw = round(float(self.v_slider_width.value()))
        else:
            tw = round(float(self.v_slider_width.value()))

        v_color_mode = self.selected_video_color_mode
        v_fullcolor_style = self.seg_v_fullcolor_style.get()
        tt = self.video_transparent_target_val

        self.btn_save_video.setEnabled(False)
        self.append_system_log(f"Starting MP4 Export Thread... [W: {tw}px, Mode: {v_color_mode}, Style: {v_fullcolor_style}, Alpha: {tt}]", "info")

        def export_thread():
            try:
                from video.exporter import export_ascii_video
                export_ascii_video(
                    video_path=fp,
                    output_path=sp,
                    target_cols=tw,
                    color_mode=v_color_mode,
                    fullcolor_style=v_fullcolor_style,
                    transparent_target=tt,
                    theme_bg_color=self.colors["bg_surface"],
                    progress_cb=lambda cur, tot, msg: self.signals.video_export_progress_signal.emit(cur, tot, msg)
                )
                self.signals.video_export_success_signal.emit(sp)
            except Exception as e:
                self.signals.video_export_error_signal.emit(str(e))

        threading.Thread(target=export_thread, daemon=True).start()

    @Slot(int, int, str)
    def _on_video_export_progress(self, current_frame, total_frames, msg):
        pct = int((current_frame / total_frames) * 100) if total_frames > 0 else 0
        filled = int((pct / 100) * 20)
        bar = "#" * filled + "-" * (20 - filled)
        log_text = f"Exporting MP4: [{bar}] {pct}% ({current_frame}/{total_frames})"
        self.append_system_log(log_text, "info", is_progress=True)

    @Slot(str)
    def _on_video_export_success(self, sp):
        self.btn_save_video.setEnabled(True)
        self.append_system_log(f"Video MP4 Export Completed: {os.path.basename(sp)}", "info")
        QMessageBox.information(self, "Export Success", f"ASCII Video saved successfully to:\n{sp}")

    @Slot(str)
    def _on_video_export_error(self, emsg):
        self.btn_save_video.setEnabled(True)
        self.append_system_log(f"Video Export Error: {emsg}", "err")
        QMessageBox.critical(self, "Export Error", f"Failed to export video:\n{emsg}")

    def convert_image_process(self, skip_dialog=False):
        self.stop_video_playback()
        self.stop_game_stream()

        if not skip_dialog or not hasattr(self, 'last_image_path'):
            fp, _ = QFileDialog.getOpenFileName(
                self,
                "Select Source Image",
                "",
                "Image Files (*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.tif *.jfif);;All Files (*.*)",
            )
            if not fp:
                self.append_system_log("Process aborted by user.", "warn")
                return
            self.last_image_path = fp
            self.last_converted_basename = os.path.splitext(os.path.basename(fp))[0]

            sp, _ = QFileDialog.getSaveFileName(
                self,
                "Save ASCII Output...",
                f"{self.last_converted_basename}_ascii.txt",
                "Text File (*.txt)",
            )
            if not sp:
                self.append_system_log("Export directory selection cancelled.", "warn")
                return
            self.last_save_path = sp
        else:
            fp = self.last_image_path
            sp = getattr(self, 'last_save_path', 'temp_ascii.txt')

        m = self.selected_color_mode
        p_style = self.seg_fullcolor_style.get()
        tt = self.transparent_target_val

        if self.chk_overdrive.isChecked():
            try:
                tw = int(self.entry_overdrive.text().strip())
                if tw <= 0:
                    raise ValueError
            except ValueError:
                self.append_system_log("Invalid Overdrive value! Reverting to default slider width.", "err")
                tw = round(float(self.slider_width.value()))
        else:
            tw = round(float(self.slider_width.value()))

        tth = round(float(self.slider_thresh.value()))
        self.btn_top_load.setEnabled(False)
        self.append_system_log(f"Rendering GPU Image ASCII... [W: {tw}px, Style: {p_style}, Cutoff: {tth}%]", "info")

        cmap = (
            {
                "Green": "#2F6B4A", "Cyan": "#1F6F86", "Pink": "#A33C4E",
                "Coral": "#B42318", "Amber": "#9A6700", "Lime": "#3B7A3A",
                "Violet": "#5B4A8A", "Blue": "#1D4ED8", "Orange": "#C2410C",
                "White": "#1C1E24", "Red": "#FF1100",
            }
            if self.current_theme == "Light"
            else {
                "Green": "#8AA090", "Cyan": "#8EB4C4", "Pink": "#C48A96",
                "Red": "#FF0000", "Coral": "#C47A7A", "Amber": "#C4A878",
                "Lime": "#9AB888", "Violet": "#A99AB8", "Blue": "#8AA0C4",
                "Orange": "#C49678", "White": "#D5DBE6",
            }
        )

        def process_thread():
            try:
                max_w = max(100, self.cached_container_w - 32)
                max_h = max(100, self.cached_container_h - 72)
                pal_hex = cmap.get(m, "#8AA090")

                pil_img, txt_res = render_image_gpu(
                    image_path=fp,
                    target_cols=tw,
                    max_ui_w=max_w,
                    max_ui_h=max_h,
                    color_mode=m,
                    fullcolor_style=p_style,
                    palette_hex=pal_hex,
                    transparent_target=tt,
                    theme_bg_color=self.colors["bg_surface"]
                )

                with open(sp, "w", encoding="utf-8") as f:
                    f.write(txt_res)

                self.signals.image_render_success_signal.emit(pil_img, txt_res, sp)
            except Exception as e:
                self.signals.image_render_error_signal.emit(str(e))

        threading.Thread(target=process_thread, daemon=True).start()

    @Slot(object, str, str)
    def _on_image_render_success(self, pil_img, txt_res, sp):
        self.current_ascii_text = txt_res
        self.current_pil_img = pil_img
        self.append_system_log(f"Render output written to: {os.path.basename(sp)}", "info")

        self.txt_ascii.hide()
        self.scroll_preview.show()

        pix = self.pil_to_qpixmap(pil_img)
        self.lbl_preview_img.setPixmap(pix)
        self.preview_photo_img = pix

        self.btn_top_load.setEnabled(True)
        self.append_system_log("GPU Image preview rendering completed smoothly.", "info")

    @Slot(str)
    def _on_image_render_error(self, emsg):
        self.append_system_log(f"Render Error: {emsg}", "err")
        QMessageBox.critical(self, "Terminal Error", f"Process failed:\n{emsg}")
        self.btn_top_load.setEnabled(True)

    def _push_game_frame(self, img):
        # Coalesce frames: never queue more than one pending UI update.
        self._latest_game_img = img
        if self._game_frame_inflight:
            return
        self._game_frame_inflight = True
        self.signals.video_frame_signal.emit(img)

    def pil_to_qpixmap(self, pil_img):
        if pil_img.mode == "RGB":
            w, h = pil_img.size
            data = pil_img.tobytes()
            return QPixmap.fromImage(QImage(data, w, h, w * 3, QImage.Format_RGB888))
        if pil_img.mode != "RGBA":
            pil_img = pil_img.convert("RGBA")
        data = pil_img.tobytes("raw", "RGBA")
        qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)

    def on_preview_canvas_click(self, event):
        if not self.is_game_playing:
            return
        if not self.game_control_active:
            self.engage_game_control()
        else:
            self.game_stream_mgr.focus_game()

    @Slot(object)
    def _on_video_frame(self, pil_img):
        if self.is_game_playing:
            self._game_frame_inflight = False
            if self._latest_game_img is not None:
                pil_img = self._latest_game_img
        elif not self.is_video_playing:
            return
        pix = self.pil_to_qpixmap(pil_img)
        self.lbl_preview_img.setPixmap(pix)
        self.preview_photo_img = pix
        if self.game_control_active and self.game_overlay._visible:
            self.game_overlay.set_frame(pix)

    @Slot()
    def _on_video_finished(self):
        btn_load_text = "#F7F4EE" if self.current_theme == "Light" else "#08090C"
        self.btn_top_video.setEnabled(True)
        self.btn_v_pause.setEnabled(False)
        self.btn_v_pause.setText("Pause")
        self.btn_v_pause.setStyleSheet(f"background-color: {self.colors['accent']}; color: {btn_load_text}; font-weight: bold; border-radius: 4px;")
        self.btn_v_stop.setEnabled(False)
        self.lbl_v_time.setText("00:00 / 00:00")
        self.v_slider_time.setValue(0)
        self.append_system_log("GPU Video playback finished.", "info")

    def start_game_stream_process(self):
        self.stop_video_playback()
        self.stop_game_stream()

        self.seg_deck_mode.set("Game")
        self.switch_deck_mode("Game")

        hwnd = self.combo_game_windows.currentData()
        if not hwnd:
            self.refresh_game_window_list()
            hwnd = self.combo_game_windows.currentData()

        if not hwnd:
            QMessageBox.warning(self, "No Game Window", "Please launch your game (e.g. Minecraft) and select its window target!")
            return

        self.is_game_playing = True

        self.btn_g_start.setEnabled(False)
        self.btn_g_stop.setEnabled(True)
        self.btn_top_game.setEnabled(False)

        self.txt_ascii.hide()
        self.scroll_preview.show()

        tt = self.game_transparent_target_val
        g_color_mode = self.selected_game_color_mode
        g_fullcolor_style = self.seg_g_fullcolor_style.get()

        win_title = self.combo_game_windows.currentText()
        self.game_stream_mgr.start_game_session(hwnd, win_title)

        self.append_system_log(f"Starting Real-Time ASCII Game Stream on Target: [{win_title}]", "info")
        QTimer.singleShot(300, self.engage_game_control)

        def run_game_loop():
            try:
                self.active_game_player = GPUAsciiGamePlayer(
                    hwnd=hwnd,
                    width_provider_fn=self.get_dynamic_preview_info,
                    style_provider_fn=lambda: self.seg_g_fullcolor_style.get(),
                    color_mode_provider_fn=lambda: self.selected_game_color_mode,
                    transparency_provider_fn=lambda: self.game_transparent_target_val,
                    transparent_target=tt,
                    color_mode=g_color_mode,
                    fullcolor_style=g_fullcolor_style,
                    theme_bg_color=self.colors["bg_surface"],
                    update_ui_cb=self._push_game_frame,
                    update_fps_cb=lambda fps: self.signals.game_fps_signal.emit(fps),
                    log_cb=lambda t, tag="info": self.append_system_log(t, tag)
                )

                self.active_game_player.run(
                    is_playing_flag_fn=lambda: self.is_game_playing
                )
            except Exception as e:
                self.append_system_log(f"Game Stream Error: {e}", "err")
            finally:
                self.active_game_player = None
                self.is_game_playing = False

        threading.Thread(target=run_game_loop, daemon=True).start()

    def convert_video_process(self):
        self.stop_game_stream()
        try:
            import cv2, moderngl
        except ImportError as e:
            self.append_system_log(f"Video conversion requires OpenCV and ModernGL ({e}).", "err")
            QMessageBox.critical(self, "Dependency Missing", "Please install dependencies:\n\npip install opencv-python moderngl")
            return

        fp, _ = QFileDialog.getOpenFileName(
            self,
            "Select Source Video",
            "",
            "Video Files (*.mp4 *.avi *.mkv *.mov);;All Files (*.*)",
        )
        if not fp:
            self.append_system_log("Video process aborted by user.", "warn")
            return

        self.stop_video_playback()
        self.preview_video_path = fp
        self.last_converted_basename = os.path.splitext(os.path.basename(fp))[0]
        self.append_system_log(f"Target video loaded for Internal GPU Offscreen Render: {os.path.basename(fp)}", "info")

        tt = self.video_transparent_target_val
        v_color_mode = self.selected_video_color_mode
        v_fullcolor_style = self.seg_v_fullcolor_style.get()

        self.is_video_playing = True
        self.is_video_paused = False

        btn_load_text = "#F7F4EE" if self.current_theme == "Light" else "#08090C"
        self.btn_top_video.setEnabled(False)
        self.btn_v_pause.setEnabled(True)
        self.btn_v_pause.setText("Pause")
        self.btn_v_pause.setStyleSheet(f"background-color: {self.colors['accent']}; color: {btn_load_text}; font-weight: bold; border-radius: 4px;")
        self.btn_v_stop.setEnabled(True)

        has_audio, audio_msg = self.audio_player.load_audio_from_video(fp)
        if not has_audio:
            self.append_system_log(f"Audio Disabled: {audio_msg}", "warn")

        self.txt_ascii.hide()
        self.scroll_preview.show()

        def run_gpu_video():
            try:
                self.active_video_player = GPUAsciiVideoPlayer(
                    video_path=fp,
                    width_provider_fn=self.get_dynamic_preview_info,
                    style_provider_fn=lambda: self.seg_v_fullcolor_style.get(),
                    color_mode_provider_fn=lambda: self.selected_video_color_mode,
                    transparency_provider_fn=lambda: self.video_transparent_target_val,
                    transparent_target=tt,
                    color_mode=v_color_mode,
                    fullcolor_style=v_fullcolor_style,
                    theme_bg_color=self.colors["bg_surface"],
                    audio_player=self.audio_player,
                    update_ui_cb=lambda img: self.signals.video_frame_signal.emit(img),
                    update_time_cb=lambda cur, tot: self.signals.video_time_signal.emit(cur, tot),
                )

                self.active_video_player.run(
                    is_playing_flag_fn=lambda: self.is_video_playing,
                    is_paused_flag_fn=lambda: self.is_video_paused,
                )
            except Exception as e:
                self.append_system_log(f"GPU Render Error: {e}", "err")
            finally:
                self.active_video_player = None
                self.is_video_playing = False
                self.is_video_paused = False
                self.signals.video_finished_signal.emit()

        threading.Thread(target=run_gpu_video, daemon=True).start()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    window = AsciiArtAppPySide6()
    window.show()
    sys.exit(app.exec())