"""
gui/dialogs.py
Settings and Convert dialogs.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton,
                               QVBoxLayout)

import updater
from gui.theme import THEMES
from gui.widgets import run_async
from version import VERSION
from remux_engine import SUPPORTED_OUTPUT
from spotify_engine import SpotifyEngine

QUALITIES = ["low", "medium", "high", "best"]


class SettingsDialog(QDialog):
    theme_previewed = Signal(str)
    update_found = Signal(object)          # updater.Release from "Check now"

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        self.cfg = cfg
        self.validated_engine = None       # set when new credentials checked OK
        self._original_theme = cfg.theme

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)

        # ── Metadata source ───────────────────────────────────────────────────
        src = QGroupBox("Look up albums on")
        src_lay = QVBoxLayout(src)
        self.source = QComboBox()
        self.source.addItem("Deezer  (free, no account needed, fast)", "deezer")
        self.source.addItem("MusicBrainz  (free, no account needed, every edition, slower)",
                            "musicbrainz")
        self.source.addItem("Spotify  (needs a developer app)", "spotify")
        self.source.setCurrentIndex(max(0, self.source.findData(cfg.metadata_source)))
        src_lay.addWidget(self.source)
        src_help = QLabel("Release choices you made for an album are kept per source.")
        src_help.setObjectName("TrackFile")
        src_lay.addWidget(src_help)
        lay.addWidget(src)

        # ── Spotify ───────────────────────────────────────────────────────────
        sp = QGroupBox("Spotify")
        self._spotify_box = sp
        form = QFormLayout(sp)
        form.setSpacing(10)
        self.client_id = QLineEdit(cfg.spotify_id)
        self.client_secret = QLineEdit(cfg.spotify_secret)
        self.client_secret.setEchoMode(QLineEdit.Password)
        show = QPushButton("Show")
        show.setProperty("variant", "small")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (
            self.client_secret.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
            show.setText("Hide" if on else "Show")))
        sec_row = QHBoxLayout()
        sec_row.addWidget(self.client_secret, 1)
        sec_row.addWidget(show)
        form.addRow("Client ID", self.client_id)
        form.addRow("Client secret", sec_row)
        help_lbl = QLabel('Create a free app at <a href="https://developer.spotify.com/dashboard">'
                          'developer.spotify.com/dashboard</a> to get these.')
        help_lbl.setObjectName("TrackFile")
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setWordWrap(True)
        form.addRow("", help_lbl)
        lay.addWidget(sp)
        self.source.currentIndexChanged.connect(self._sync_source)
        self._sync_source()

        # ── Appearance ────────────────────────────────────────────────────────
        ap = QGroupBox("Appearance")
        ap_form = QFormLayout(ap)
        self.theme = QComboBox()
        self.theme.addItems(list(THEMES))
        self.theme.setCurrentText(cfg.theme if cfg.theme in THEMES else "Dark")
        self.theme.currentTextChanged.connect(self.theme_previewed)
        ap_form.addRow("Theme", self.theme)
        lay.addWidget(ap)

        # ── Auto-convert ──────────────────────────────────────────────────────
        rx = QGroupBox("Convert before renaming")
        rx_lay = QVBoxLayout(rx)
        self.remux = QCheckBox("Convert files that aren't MP3 or FLAC when I press Rename && Tag")
        self.remux.setChecked(cfg.auto_remux)
        rx_lay.addWidget(self.remux)
        opts = QHBoxLayout()
        self.remux_fmt = QComboBox()
        self.remux_fmt.addItems(sorted(SUPPORTED_OUTPUT))
        self.remux_fmt.setCurrentText(cfg.auto_remux_target)
        self.remux_q = QComboBox()
        self.remux_q.addItems(QUALITIES)
        self.remux_q.setCurrentText(cfg.auto_remux_quality)
        opts.addWidget(QLabel("Format"))
        opts.addWidget(self.remux_fmt)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Quality"))
        opts.addWidget(self.remux_q)
        opts.addStretch()
        rx_lay.addLayout(opts)
        self.remux_del = QCheckBox("Delete the original after converting (Undo can't bring it back)")
        self.remux_del.setChecked(cfg.auto_remux_delete_source)
        rx_lay.addWidget(self.remux_del)
        self.remux.toggled.connect(self._sync_remux)
        self._sync_remux(self.remux.isChecked())
        lay.addWidget(rx)

        # ── Updates ───────────────────────────────────────────────────────────
        up = QGroupBox("Updates")
        up_lay = QVBoxLayout(up)
        self.check_updates = QCheckBox("Check for a new version when ArtiSync starts")
        self.check_updates.setChecked(cfg.check_updates)
        up_lay.addWidget(self.check_updates)
        up_row = QHBoxLayout()
        self.update_status = QLabel(f"You have version {VERSION}.")
        self.update_status.setObjectName("TrackFile")
        self.update_status.setWordWrap(True)
        self.check_btn = QPushButton("Check now")
        self.check_btn.setProperty("variant", "small")
        self.check_btn.clicked.connect(self._check_now)
        up_row.addWidget(self.update_status, 1)
        up_row.addWidget(self.check_btn)
        up_lay.addLayout(up_row)
        lay.addWidget(up)

        self.error = QLabel()
        self.error.setObjectName("Chip")
        self.error.setProperty("tone", "bad")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setProperty("variant", "primary")
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def _sync_source(self, *_):
        self._spotify_box.setVisible(self.source.currentData() == "spotify")
        self.adjustSize()
        if hasattr(self, "error"):          # not built yet on the first call
            self.error.hide()

    def _sync_remux(self, on):
        for w in (self.remux_fmt, self.remux_q, self.remux_del):
            w.setEnabled(on)

    def _check_now(self):
        self.check_btn.setEnabled(False)
        self.update_status.setText("Checking…")

        def done(rel, err):
            if not self.isVisible():
                return
            self.check_btn.setEnabled(True)
            if err is not None:
                self.update_status.setText(str(err) if isinstance(err, updater.UpdateError)
                                           else f"Couldn't check ({err}).")
            elif rel is None:
                self.update_status.setText(f"You have the latest version ({VERSION}).")
            else:
                self.update_status.setText(f"ArtiSync {rel.version} is available.")
                self.update_found.emit(rel)

        run_async(updater.check, done)

    def reject(self):
        if self.theme.currentText() != self._original_theme:
            self.theme_previewed.emit(self._original_theme)
        super().reject()

    def _save(self):
        cid, sec = self.client_id.text().strip(), self.client_secret.text().strip()
        changed = (cid, sec) != (self.cfg.spotify_id, self.cfg.spotify_secret)
        if self.source.currentData() == "spotify" and not (cid and sec):
            self.error.setText("Spotify needs a Client ID and secret. "
                               "Enter them, or choose Deezer or MusicBrainz.")
            self.error.show()
            return
        if not (changed and cid and sec) or self.source.currentData() != "spotify":
            self._finish(cid, sec)
            return
        save_btn = self.buttons.button(QDialogButtonBox.Save)
        save_btn.setEnabled(False)
        save_btn.setText("Checking…")

        def done(engine, err):
            save_btn.setEnabled(True)
            save_btn.setText("Save")
            if err or not engine.is_configured:
                self.error.setText("Spotify didn't accept those credentials. "
                                   "Check the Client ID and secret and try again.")
                self.error.show()
                return
            self.validated_engine = engine
            self._finish(cid, sec)

        run_async(lambda: SpotifyEngine(cid, sec), done)

    def _finish(self, cid, sec):
        c = self.cfg
        c.spotify_id, c.spotify_secret = cid, sec
        c.metadata_source = self.source.currentData()
        c.theme = self.theme.currentText()
        c.check_updates = self.check_updates.isChecked()
        c.auto_remux = self.remux.isChecked()
        c.auto_remux_target = self.remux_fmt.currentText()
        c.auto_remux_quality = self.remux_q.currentText()
        c.auto_remux_delete_source = self.remux_del.isChecked() and c.auto_remux
        self.accept()


class ConvertDialog(QDialog):
    """Convert selected files in one album folder with FFmpeg."""

    def __init__(self, folder, files, remux_engine, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Convert files")
        self.resize(560, 560)
        self._folder, self._remux = folder, remux_engine
        self.converted = 0
        self._running = False      # a conversion worker is active
        self._stop = False         # Cancel pressed while running

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        opts = QHBoxLayout()
        self.fmt = QComboBox()
        self.fmt.addItems(sorted(SUPPORTED_OUTPUT))
        self.fmt.setCurrentText(".flac")
        self.q = QComboBox()
        self.q.addItems(QUALITIES)
        self.q.setCurrentText("best")
        opts.addWidget(QLabel("Convert to"))
        opts.addWidget(self.fmt)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Quality"))
        opts.addWidget(self.q)
        opts.addStretch()
        lay.addLayout(opts)

        self.delete = QCheckBox("Delete the originals after converting")
        lay.addWidget(self.delete)

        head = QHBoxLayout()
        lbl = QLabel("FILES")
        lbl.setObjectName("SectionLabel")
        head.addWidget(lbl)
        head.addStretch()
        self.toggle = QPushButton("Select none")
        self.toggle.setProperty("variant", "small")
        self.toggle.clicked.connect(self._toggle_all)
        head.addWidget(self.toggle)
        lay.addLayout(head)

        self.list = QListWidget()
        for f in files:
            it = QListWidgetItem(f)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.status = QLabel("Ready")
        self.status.setObjectName("ProgressText")
        lay.addWidget(self.progress)
        lay.addWidget(self.status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.run_btn = self.buttons.addButton("Convert", QDialogButtonBox.AcceptRole)
        self.run_btn.setProperty("variant", "primary")
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def reject(self):
        if self._running:
            # Don't close under a running conversion: stop after this file.
            self._stop = True
            self.status.setText("Stopping after the current file…")
            return
        super().reject()

    def _toggle_all(self):
        any_unchecked = any(self.list.item(i).checkState() != Qt.Checked
                            for i in range(self.list.count()))
        state = Qt.Checked if any_unchecked else Qt.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self.toggle.setText("Select none" if any_unchecked else "Select all")

    def _start(self):
        files = [self.list.item(i).text() for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.Checked]
        if not files:
            self.status.setText("Tick at least one file.")
            return
        fmt, q, delete = self.fmt.currentText(), self.q.currentText(), self.delete.isChecked()
        for w in (self.run_btn, self.list, self.fmt, self.q, self.delete, self.toggle):
            w.setEnabled(False)
        self.progress.setRange(0, len(files))
        self._running = True

        def work(report):
            errors, ok = [], 0
            for i, f in enumerate(files):
                if self._stop:
                    break
                report(i, len(files), f"Converting {i + 1} of {len(files)}: {f}")
                src = os.path.join(self._folder, f)
                dst = self._remux.suggested_output_path(src, fmt)
                if dst == src or os.path.lexists(dst):
                    # FFmpeg runs with -y; never let it clobber an existing file.
                    errors.append(f"{f}: '{os.path.basename(dst)}' already exists — not converted")
                    continue
                r = self._remux.convert(src, dst, quality=q, delete_source=delete)
                if r is True:
                    ok += 1
                else:
                    errors.append(f"{f}: {r}")
            report(len(files), len(files), "")
            return ok, errors

        def progress(i, n, text):
            self.progress.setValue(i)
            if text:
                self.status.setText(text)

        def done(res, exc):
            self._running = False
            ok, errors = res if exc is None else (0, [str(exc)])
            self.converted = ok
            if self._stop:
                super(ConvertDialog, self).reject()
                return
            if errors:
                self.status.setText(f"{self.converted} of {len(files)} converted. "
                                    f"Problems:\n" + "\n".join(errors[:6]))
                self.buttons.button(QDialogButtonBox.Cancel).setText("Close")
            else:
                self.accept()

        run_async(work, done, progress)
