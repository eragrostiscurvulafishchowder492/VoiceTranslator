"""入口：python -m app.main"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from PySide6.QtWidgets import QApplication
    from app.config import AppSettings
    from app.gui.main_window import MainWindow

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    settings = AppSettings.load()
    app = QApplication(sys.argv)
    app.setApplicationName("Real-Time Voice")
    win = MainWindow(settings)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()