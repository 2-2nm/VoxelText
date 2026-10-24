"""Custom widgets: the in-game input overlay and the segmented button."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QPushButton, QHBoxLayout

from game.manager import make_overlay_window, place_overlay_window, hide_overlay_window


class GameOverlayWindow(QWidget):
    def __init__(self):
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: #000000;")
        self.setGeometry(-32000, -32000, 64, 64)
        self._label = QLabel(self)
        self._label.setScaledContents(True)
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._styled = False
        self._visible = False
        self._last_rect = None
        self.create()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._label.setGeometry(0, 0, self.width(), self.height())

    def set_frame(self, pix):
        self._label.setPixmap(pix)

    def show_at(self, rect):
        hwnd = int(self.winId())
        if not self._styled:
            self.show()
            make_overlay_window(hwnd)
            self._styled = True
        if not self._visible or self._last_rect != rect:
            place_overlay_window(hwnd, *rect)
            self._visible = True
            self._last_rect = rect

    def hide_overlay(self):
        if self._visible:
            hide_overlay_window(int(self.winId()))
            self._visible = False
            self._last_rect = None


class SegmentedButton(QFrame):
    valueChanged = Signal(str)

    def __init__(self, items, default=None, selected_color="#D5DBE6", unselected_color="#1C2028", text_selected="#08090C", text_unselected="#E6E8EE", parent=None):
        super().__init__(parent)
        self.items = items
        self.selected_value = default or (items[0] if items else "")
        self.buttons = {}
        self.selected_color = selected_color
        self.unselected_color = unselected_color
        self.text_selected = text_selected
        self.text_unselected = text_unselected

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(2)
        self.setStyleSheet("background-color: transparent; border: none;")

        for item in self.items:
            btn = QPushButton(item)
            btn.setFixedHeight(22)
            btn.setFont(QFont("Consolas", 9, QFont.Bold))
            btn.clicked.connect(lambda checked=False, val=item: self.set(val, emit=True))
            self.layout.addWidget(btn)
            self.buttons[item] = btn

        self.update_states()

    def set_colors(self, selected_color, unselected_color, text_selected, text_unselected):
        self.selected_color = selected_color
        self.unselected_color = unselected_color
        self.text_selected = text_selected
        self.text_unselected = text_unselected
        self.update_states()

    def set(self, value, emit=False):
        if value in self.buttons:
            self.selected_value = value
            self.update_states()
            if emit:
                self.valueChanged.emit(value)

    def get(self):
        return self.selected_value

    def update_states(self):
        for val, btn in self.buttons.items():
            if val == self.selected_value:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {self.selected_color};
                        color: {self.text_selected};
                        border: none;
                        border-radius: 11px;
                        padding: 2px 10px;
                        font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {self.unselected_color};
                        color: {self.text_unselected};
                        border: none;
                        border-radius: 11px;
                        padding: 2px 10px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background-color: #2A2F3A;
                    }}
                """)

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        for btn in self.buttons.values():
            btn.setEnabled(enabled)
