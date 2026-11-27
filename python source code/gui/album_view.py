"""
gui/album_view.py
Centre column: the open album. A header with match stats, then one row per
Spotify track showing which file matched and what it will be renamed to.
Pairing is inline: each row has a menu to pick / change / remove its file,
and leftover files have a menu to assign them to a missing track.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QScrollArea, QStackedWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from gui.widgets import ElidedLabel


def _chip(text, tone=None):
    c = QLabel(text)
    c.setObjectName("Chip")
    if tone:
        c.setProperty("tone", tone)
    return c


class _TrackRow(QFrame):
    def __init__(self, row, preview, view):
        super().__init__()
        self.setObjectName("TrackRow")
        t = row.track
        if not row.file:
            self.setProperty("state", "missing")
        elif row.score < 55:
            self.setProperty("state", "warn")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(12)

        num = QLabel(f"{t['num']}" if t.get("disc", 1) == 1 else f"{t['disc']}·{t['num']}")
        num.setObjectName("TrackNum")
        num.setFixedWidth(28)
        num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(num)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = ElidedLabel(t["name"])
        title.setObjectName("TrackTitle")
        text.addWidget(title)
        if not row.file:
            sub = "No file"
        elif row.already_named:
            sub = row.file
        else:
            sub = f"{row.file}   →   {row.new_name}"
        file_lbl = ElidedLabel(sub, mode=Qt.ElideMiddle)
        file_lbl.setObjectName("TrackFile")
        text.addWidget(file_lbl)
        lay.addLayout(text, 1)

        if row.file:
            score = QLabel()
            score.setObjectName("Score")
            if row.already_named:
                score.setText("✓ named")
                score.setProperty("tone", "done")
            else:
                score.setText(f"{row.score}%")
                score.setProperty("tone", "ok" if row.score >= 80
                                  else "warn" if row.score >= 55 else "bad")
            lay.addWidget(score)

        btn = QPushButton("Change" if row.file else "Assign")
        btn.setProperty("variant", "small")
        btn.setCursor(Qt.PointingHandCursor)
        menu = QMenu(btn)
        loose = preview.unmatched_files
        if loose:
            menu.addSection("Unmatched files")
            for f in loose:
                menu.addAction(f, lambda f=f: view.assign_requested.emit(row.key, f))
        others = [r.file for r in preview.rows if r.file and r.key != row.key]
        if others:
            sub_menu = menu.addMenu("Take from another track")
            for f in sorted(others, key=str.casefold):
                sub_menu.addAction(f, lambda f=f: view.assign_requested.emit(row.key, f))
        if row.file:
            menu.addSeparator()
            menu.addAction("Remove match", lambda: view.unassign_requested.emit(row.key))
        if menu.isEmpty():
            menu.addAction("No files available").setEnabled(False)
        btn.setMenu(menu)
        lay.addWidget(btn)


class _LooseFileRow(QFrame):
    """A file in the folder that isn't matched to any track."""

    def __init__(self, filename, preview, view):
        super().__init__()
        self.setObjectName("TrackRow")
        self.setProperty("state", "loose")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(12)
        name = ElidedLabel(filename, mode=Qt.ElideMiddle)
        name.setObjectName("TrackTitle")
        lay.addWidget(name, 1)
        note = QLabel("left as is")
        note.setObjectName("TrackFile")
        lay.addWidget(note)

        btn = QPushButton("Assign to")
        btn.setProperty("variant", "small")
        btn.setCursor(Qt.PointingHandCursor)
        menu = QMenu(btn)
        missing = preview.missing
        if missing:
            menu.addSection("Missing tracks")
            for r in missing:
                menu.addAction(f"{r.track['num']}. {r.track['name']}",
                               lambda r=r: view.assign_requested.emit(r.key, filename))
        taken = preview.matched
        if taken:
            sub = menu.addMenu("Replace a matched track")
            for r in taken:
                sub.addAction(f"{r.track['num']}. {r.track['name']}",
                              lambda r=r: view.assign_requested.emit(r.key, filename))
        btn.setMenu(menu)
        lay.addWidget(btn)


class AlbumView(QWidget):
    assign_requested   = Signal(object, str)    # row key, filename
    unassign_requested = Signal(object)         # row key

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 0)
        lay.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        self.title = ElidedLabel("")
        self.title.setObjectName("AlbumTitle")
        self.sub = ElidedLabel("")
        self.sub.setObjectName("AlbumSub")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        bar.addLayout(self._chips)
        bar.addStretch()
        seg = QFrame()
        seg.setObjectName("Segmented")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)
        self._tab_tracks = QPushButton("Tracks")
        self._tab_log = QPushButton("Log")
        for i, b in enumerate((self._tab_tracks, self._tab_log)):
            b.setProperty("variant", "segment")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self._pages.setCurrentIndex(i))
            seg_lay.addWidget(b)
        self._tab_tracks.setChecked(True)
        bar.addWidget(seg)
        lay.addLayout(bar)

        # ── Pages: tracks / log / message ─────────────────────────────────────
        self._pages = QStackedWidget()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._rows_host = QWidget()
        self._rows_host.setObjectName("RowsHost")
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 4, 8, 16)
        self._rows.setSpacing(6)
        self._scroll.setWidget(self._rows_host)
        self._pages.addWidget(self._scroll)

        self._log = QTextEdit()
        self._log.setObjectName("Log")
        self._log.setReadOnly(True)
        self._pages.addWidget(self._log)

        msg_page = QWidget()
        msg_lay = QVBoxLayout(msg_page)
        msg_lay.addStretch()
        self._msg = QLabel()
        self._msg.setObjectName("EmptyState")
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)
        msg_lay.addWidget(self._msg)
        self._msg_btn = QPushButton()
        self._msg_btn.setProperty("variant", "primary")
        self._msg_btn.clicked.connect(lambda: self._msg_action and self._msg_action())
        self._msg_action = None
        self._msg_btn.hide()
        msg_lay.addWidget(self._msg_btn, 0, Qt.AlignHCenter)
        msg_lay.addStretch(2)
        self._pages.addWidget(msg_page)
        lay.addWidget(self._pages, 1)

        self.show_message("Pick an album from the library.")

    # ── States ────────────────────────────────────────────────────────────────

    def set_heading(self, title, sub=""):
        self.title.setText(title)
        self.sub.setText(sub)

    def show_message(self, text, button_text=None, action=None):
        self._clear_chips()
        self._msg.setText(text)
        self._msg_action = action
        if button_text:
            self._msg_btn.setText(button_text)
            self._msg_btn.show()
        else:
            self._msg_btn.hide()
        self._pages.setCurrentIndex(2)

    def show_preview(self, preview):
        # Keep the scroll position when re-rendering the same album.
        keep = self._pages.currentIndex() == 0
        pos = self._scroll.verticalScrollBar().value() if keep else 0

        self._clear_chips()
        n = len(preview.rows)
        matched, missing = len(preview.matched), len(preview.missing)
        loose, pending = len(preview.unmatched_files), len(preview.pending)
        self._chips.addWidget(_chip(f"{matched} / {n} matched",
                                    "ok" if matched == n else None))
        if missing:
            self._chips.addWidget(_chip(f"{missing} missing", "bad"))
        if loose:
            self._chips.addWidget(_chip(f"{loose} unmatched file{'s' * (loose != 1)}", "warn"))
        if pending:
            self._chips.addWidget(_chip(f"{pending} to rename"))
        elif matched and not loose:
            self._chips.addWidget(_chip("All named", "ok"))

        while self._rows.count():
            w = self._rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        for row in preview.rows:
            self._rows.addWidget(_TrackRow(row, preview, self))
        if preview.unmatched_files:
            lbl = QLabel(f"FILES NOT MATCHED TO A TRACK  ({loose})")
            lbl.setObjectName("SectionLabel")
            lbl.setContentsMargins(4, 14, 0, 2)
            self._rows.addWidget(lbl)
            for f in preview.unmatched_files:
                self._rows.addWidget(_LooseFileRow(f, preview, self))
        self._rows.addStretch()

        self._log.setPlainText(preview.log)
        self._pages.setCurrentIndex(1 if self._tab_log.isChecked() else 0)
        if keep:
            QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(pos))

    def _clear_chips(self):
        while self._chips.count():
            w = self._chips.takeAt(0).widget()
            if w:
                w.deleteLater()
