import os
import sys
import platform

MAX_WORKERS = os.cpu_count() or 8
APP_NAME = "VoxelText"


def _is_frozen():
    return bool(getattr(sys, "frozen", False))


def project_root():
    if _is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path):
    base = project_root()
    for sub in ("assets", "data", ""):
        candidate = os.path.join(base, sub, relative_path)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(base, "assets", relative_path)


def get_config_path():
    if platform.system() == "Windows":
        base_dir = os.getenv("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base_dir = os.path.join(os.path.expanduser("~"), ".config")
    config_dir = os.path.join(base_dir, APP_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "settings.json")


def hex_to_rgb_float(hex_str):
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def hex_to_rgb_int(hex_str):
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))
