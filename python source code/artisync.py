"""
artisync.py — ArtiSync (Qt / PySide6 GUI).

    pip install PySide6 spotipy thefuzz mutagen
    python artisync.py

(or ./run.sh from the repository root, which sets up its own environment)
"""

import os
import sys

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_config import AppConfig          # noqa: E402
from gui.main_window import MainWindow    # noqa: E402


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ArtiSync")
    app.setOrganizationName("ArtiSync")
    app.setDesktopFileName("com.artisync.ArtiSync")
    app.setStyle("Fusion")
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ArtiSync.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))

    win = MainWindow(AppConfig.load())
    win.show()
    code = app.exec()
    # Tear down in a fixed order: let background jobs finish (they bail out
    # quickly once the window is closing), then destroy the window before
    # the QApplication goes away. Leaving this to Python's garbage collector
    # can crash on exit.
    QThreadPool.globalInstance().waitForDone(3000)
    win.deleteLater()
    del win
    app.processEvents()
    # Then leave without running Python's interpreter shutdown: PySide6's
    # exit-time cleanup walks every remaining wrapper and can delete Qt
    # objects Qt already deleted ("shared QObject was deleted directly"),
    # which crashes with SIGBUS/SIGSEGV now and then. Everything is already
    # saved by this point (settings on change, album status immediately,
    # window geometry in closeEvent), so skipping it loses nothing.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
