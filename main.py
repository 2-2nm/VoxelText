import sys
import os
import argparse
import ctypes
import multiprocessing


def enable_high_performance_gpu():
    if sys.platform == "win32":
        try:
            ctypes.c_ulong.in_dll(ctypes.CDLL("nvapi64.dll"), "NvOptimusEnablement").value = 0x00000001
        except Exception:
            pass
        try:
            ctypes.c_int.in_dll(ctypes.CDLL("atiagd64.dll"), "AmdPowerXpressRequestHighPerformance").value = 1
        except Exception:
            pass


def init_qt_environment():
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"


def main():
    multiprocessing.freeze_support()
    enable_high_performance_gpu()
    init_qt_environment()

    parser = argparse.ArgumentParser(
        description="VoxelText - High-performance GPU ASCII Art Generator & Video Converter"
    )
    parser.add_argument(
        "--version", "-v", action="version", version="VoxelText v2.6.0"
    )
    parser.add_argument(
        "--image", "-i", type=str, help="Input image file path for CLI ASCII conversion"
    )
    parser.add_argument(
        "--output", "-o", type=str, help="Output TXT file path for CLI conversion result"
    )
    parser.add_argument(
        "--width", "-w", type=int, default=85, help="ASCII character width (default: 85)"
    )

    args = parser.parse_args()

    if args.image:
        from core import convert_image_to_ascii_str

        if not os.path.exists(args.image):
            print(f"[ERROR] Input image file not found: {args.image}")
            sys.exit(1)

        print(f"[INFO] Processing image '{args.image}' to ASCII (width={args.width} columns)...")
        try:
            ascii_result = convert_image_to_ascii_str(args.image, new_width=args.width)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(ascii_result)
                print(f"[SUCCESS] ASCII result saved to '{args.output}'")
            else:
                print("\n" + ascii_result + "\n")
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR] Conversion failed: {e}")
            sys.exit(1)

    from PySide6.QtWidgets import QApplication
    from gui import AsciiArtAppPySide6

    app = QApplication(sys.argv)
    app.setApplicationName("VoxelText")
    app.setOrganizationName("VoxelText Engine")

    window = AsciiArtAppPySide6()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()