"""
gui/update_dialog.py
Shows a newer release and installs it (see updater.py for how each kind of
install is updated).
"""

import threading

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QProgressBar,
                               QTextBrowser, QVBoxLayout)

import updater
from gui.widgets import run_async
from version import VERSION


def downloads_dir():
    return (QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
            or QStandardPaths.writableLocation(QStandardPaths.HomeLocation))


class UpdateDialog(QDialog):
    """After exec(): .skipped if the user skipped this version, .restart if
    the update is in place and the app should close now."""

    def __init__(self, release, can_quit, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update ArtiSync")
        self.resize(560, 480)
        self._rel = release
        self._plan = updater.plan(release)
        self._can_quit = can_quit          # False while files are being renamed
        self._cancel = threading.Event()
        self._running = False
        self.skipped = False
        self.restart = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        title = QLabel(f"ArtiSync {release.version} is available")
        title.setObjectName("AlbumTitle")
        lay.addWidget(title)
        sub = QLabel(f"You have version {VERSION}. {self._explain()}")
        sub.setObjectName("AlbumSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        notes = QTextBrowser()
        notes.setObjectName("ReleaseNotes")
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes.strip() or "_No release notes._")
        lay.addWidget(notes, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status = QLabel()
        self.status.setObjectName("ProgressText")
        self.status.setWordWrap(True)
        self.status.hide()
        lay.addWidget(self.progress)
        lay.addWidget(self.status)

        self.buttons = QDialogButtonBox()
        self.skip_btn = self.buttons.addButton("Skip this version",
                                               QDialogButtonBox.DestructiveRole)
        self.later_btn = self.buttons.addButton("Later", QDialogButtonBox.RejectRole)
        self.go_btn = self.buttons.addButton(
            {"install": "Update and restart", "download": "Download",
             "page": "Open download page"}[self._plan.action],
            QDialogButtonBox.AcceptRole)
        self.go_btn.setProperty("variant", "primary")
        self.go_btn.setDefault(True)
        self.skip_btn.clicked.connect(self._skip)
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._go)
        lay.addWidget(self.buttons)

    def _explain(self):
        kind, action = self._plan.kind, self._plan.action
        if action == "install":
            return "ArtiSync will download it, close, and reopen updated."
        if kind == "flatpak":
            return ("Flatpak apps can't update themselves; ArtiSync will save the "
                    "new version to your Downloads folder and open it so you can install it.")
        if action == "download":
            return ("ArtiSync can't replace itself where it's installed, so the new "
                    "version will be saved to your Downloads folder.")
        if kind == "source":
            return "You're running from source: update with git pull, or download a build."
        return "Download it from the release page."

    def _say(self, text):
        self.status.setText(text)
        self.status.show()

    def _skip(self):
        self.skipped = True
        self.reject()

    def reject(self):
        if self._running:
            self._cancel.set()
            self._say("Cancelling…")
            return
        super().reject()

    def _go(self):
        p = self._plan
        if p.action == "page":
            QDesktopServices.openUrl(QUrl(self._rel.page_url))
            self.accept()
            return
        if p.action == "install" and not self._can_quit():
            self._say("ArtiSync is renaming or tagging files. Update once that has finished.")
            return
        self._running = True
        self._cancel.clear()
        self.go_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.later_btn.setText("Cancel")
        self.progress.setRange(0, 0)
        self.progress.show()
        self._say(f"Downloading {p.asset.name}…")
        dest, cancel = downloads_dir(), self._cancel

        def work(report):
            return updater.fetch(p, dest, lambda d, t: report(d, t, ""), cancel)

        run_async(work, self._fetched, self._progress)

    def _progress(self, done, total, _text):
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
            self.status.setText(f"Downloading {self._plan.asset.name}…  "
                                f"{done / 1e6:.1f} of {total / 1e6:.1f} MB")

    def _fetched(self, path, err):
        self._running = False
        self.later_btn.setText("Later")
        self.progress.hide()
        if err is not None:
            self.go_btn.setEnabled(True)
            self.skip_btn.setEnabled(True)
            if isinstance(err, updater.Cancelled):
                self.status.hide()
            else:
                self._say(str(err) if isinstance(err, updater.UpdateError)
                          else f"Download failed ({err}).")
            return
        p = self._plan
        if p.action == "download":
            if p.kind == "flatpak":
                # Opens it in the software centre (GNOME Software, Discover…).
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                self._say(f"Saved to {path}. If no installer opened, run:\n"
                          f"flatpak install --user --reinstall \"{path}\"")
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
                self._say(f"Saved to {path}.")
            self.go_btn.hide()
            self.skip_btn.hide()
            self.later_btn.setText("Close")
            return
        if not self._can_quit():
            self.go_btn.setEnabled(True)
            self._say("ArtiSync is renaming or tagging files. Update once that has finished.")
            return
        try:
            self.restart = updater.apply(p, path)
        except updater.UpdateError as e:
            self.go_btn.setEnabled(True)
            self.skip_btn.setEnabled(True)
            self._say(str(e))
            return
        self.accept()
