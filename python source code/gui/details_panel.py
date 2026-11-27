"""
gui/details_panel.py
Right column: cover art, release metadata, and what gets written to files.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from gui.widgets import ArtView


class DetailsPanel(QWidget):
    options_changed = Signal(bool, bool, bool)     # art, tags, genre
    numbering_changed = Signal(bool)
    reload_art = Signal()

    def __init__(self, pal, art=True, tags=True, genre=True, numbers=True, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(14)

        self.art = ArtView(pal)
        lay.addWidget(self.art)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self._values = {}
        for i, key in enumerate(("Artist", "Album", "Year", "Genre")):
            k = QLabel(key.upper())
            k.setObjectName("DetailKey")
            v = QLabel("—")
            v.setObjectName("DetailValue")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(k, i, 0, Qt.AlignTop | Qt.AlignLeft)
            grid.addWidget(v, i, 1)
            self._values[key.lower()] = v
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        hdr = QLabel("WRITE TO FILES")
        hdr.setObjectName("DetailKey")
        lay.addWidget(hdr)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chips = {}
        for key, label, on in (("art", "Artwork", art), ("tags", "Tags", tags),
                               ("genre", "Genre", genre)):
            b = QPushButton(label)
            b.setProperty("variant", "chip")
            b.setCheckable(True)
            b.setChecked(on)
            b.setCursor(Qt.PointingHandCursor)
            b.toggled.connect(self._emit_options)
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(label) + 26)
            chips.addWidget(b)
            self._chips[key] = b
        chips.addStretch()
        lay.addLayout(chips)

        hdr2 = QLabel("FILE NAMES")
        hdr2.setObjectName("DetailKey")
        lay.addWidget(hdr2)
        name_row = QHBoxLayout()
        self.numbers = QPushButton("Track numbers")
        self.numbers.setProperty("variant", "chip")
        self.numbers.setCheckable(True)
        self.numbers.setChecked(numbers)
        self.numbers.setCursor(Qt.PointingHandCursor)
        self.numbers.setToolTip("On: 01 - Song.mp3     Off: Song.mp3")
        self.numbers.toggled.connect(self.numbering_changed)
        name_row.addWidget(self.numbers)
        name_row.addStretch()
        lay.addLayout(name_row)

        reload_btn = QPushButton("Reload artwork")
        reload_btn.setProperty("variant", "ghost")
        reload_btn.setCursor(Qt.PointingHandCursor)
        reload_btn.clicked.connect(self.reload_art)
        lay.addWidget(reload_btn, 0, Qt.AlignLeft)
        lay.addStretch()

    def _emit_options(self):
        self.options_changed.emit(*(self._chips[k].isChecked()
                                    for k in ("art", "tags", "genre")))

    def set_metadata(self, meta):
        meta = meta or {}
        for k, v in self._values.items():
            v.setText(str(meta.get(k) or "—"))

    def clear(self, art_text=""):
        self.set_metadata({})
        self.art.set_pixmap(None, art_text)
