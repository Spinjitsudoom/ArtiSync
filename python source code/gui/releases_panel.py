"""
gui/releases_panel.py
Second column: the current artist's releases (Spotify or MusicBrainz), with artwork.
Clicking one overrides the release auto-detect picked for the open album.

The box at the top filters that list as you type; Enter (or the button
under it) searches the whole source instead, for releases filed under a
different artist. Clearing the box goes back to the artist's releases.
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath,
                           QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QLineEdit, QListView, QPushButton, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from gui.widgets import placeholder_art, rounded

RELEASE_ROLE = Qt.UserRole + 1
THUMB_ROLE   = Qt.UserRole + 2
THUMB = 52
ROW_H = 68


class _ReleaseDelegate(QStyledItemDelegate):
    def __init__(self, pal, parent=None):
        super().__init__(parent)
        self.pal = pal

    def sizeHint(self, _opt, _idx):
        return QSize(200, ROW_H)

    def paint(self, p, opt, idx):
        rel = idx.data(RELEASE_ROLE)
        if rel is None:
            return
        pal = self.pal
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(4, 2, -4, -2)

        selected = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            p.fillPath(path, QColor(pal["selection"] if selected else pal["card_hover"]))
        if selected:
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(r.left(), r.top() + 12, 3, r.height() - 24), 1.5, 1.5)
            p.fillPath(bar, QColor(pal["accent"]))

        thumb = idx.data(THUMB_ROLE)
        tx, ty = r.left() + 10, r.top() + (r.height() - THUMB) / 2
        p.drawPixmap(int(tx), int(ty),
                     thumb if thumb is not None else placeholder_art(THUMB, pal, 6))

        text_x = tx + THUMB + 12
        text_w = r.right() - text_x - 10
        title_f = QFont(opt.font)
        title_f.setPixelSize(14)
        title_f.setWeight(QFont.DemiBold if selected else QFont.Medium)
        p.setFont(title_f)
        p.setPen(QColor(pal["selection_text"] if selected else pal["text"]))
        fm = p.fontMetrics()
        title = fm.elidedText(rel["title"], Qt.ElideRight, int(text_w))
        p.drawText(QRectF(text_x, r.top() + 13, text_w, 20),
                   Qt.AlignLeft | Qt.AlignVCenter, title)

        sub_f = QFont(opt.font)
        sub_f.setPixelSize(12)
        p.setFont(sub_f)
        p.setPen(QColor(pal["muted"]))
        bits = [rel.get("artist", ""), rel.get("year", "")]
        rtype = rel.get("type") or ""             # engines give display case
        if rtype and rtype != "Album":
            bits.append(rtype)
        n = rel.get("track_count")
        if n not in (None, "?"):
            bits.append(f"{n} track{'s' if n != 1 else ''}")
        sub = p.fontMetrics().elidedText("  ·  ".join(b for b in bits if b),
                                         Qt.ElideRight, int(text_w))
        p.drawText(QRectF(text_x, r.top() + 35, text_w, 18),
                   Qt.AlignLeft | Qt.AlignVCenter, sub)
        p.restore()


class ReleasesPanel(QWidget):
    release_chosen = Signal(object)          # release dict
    search_requested = Signal(str)           # query for a search of the whole source

    def __init__(self, pal, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._items = {}                     # release id → item (shown list)
        self._thumbs = {}                    # release id → rounded pixmap
        self._artist_releases = []
        self._searching = False              # showing search results
        self._source = "Spotify"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 12, 6, 8)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 8, 0)
        title = QLabel("RELEASES")
        title.setObjectName("PanelHeader")
        self._badge = QLabel("0")
        self._badge.setObjectName("Badge")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._badge)
        lay.addLayout(head)

        box = QVBoxLayout()
        box.setContentsMargins(8, 0, 8, 0)
        box.setSpacing(6)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_text)
        self.search.returnPressed.connect(self._request_search)
        box.addWidget(self.search)

        self._search_btn = QPushButton()
        self._search_btn.setProperty("variant", "small")
        self._search_btn.setCursor(Qt.PointingHandCursor)
        self._search_btn.clicked.connect(self._request_search)
        self._search_btn.hide()
        box.addWidget(self._search_btn)

        self._back_btn = QPushButton("←  Back to the artist's releases")
        self._back_btn.setProperty("variant", "ghost")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.clicked.connect(self.search.clear)
        self._back_btn.hide()
        box.addWidget(self._back_btn, 0, Qt.AlignLeft)
        lay.addLayout(box)

        self._hint = QLabel("Click a release to use it for this album.")
        self._hint.setObjectName("TrackFile")
        self._hint.setContentsMargins(8, 0, 8, 2)
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)

        self._model = QStandardItemModel(self)
        self.view = QListView()
        self.view.setObjectName("ReleaseList")
        self.view.setModel(self._model)
        self.view.setMouseTracking(True)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setUniformItemSizes(True)
        self._delegate = _ReleaseDelegate(pal, self.view)
        self.view.setItemDelegate(self._delegate)
        self.view.clicked.connect(lambda i: self.release_chosen.emit(i.data(RELEASE_ROLE)))
        lay.addWidget(self.view, 1)
        self.set_source(self._source)

    # ── Public ────────────────────────────────────────────────────────────────

    @property
    def searching(self):
        return self._searching

    def set_source(self, name):
        """Name of the metadata source, for the box's wording."""
        self._source = name
        self.search.setPlaceholderText(f"Filter, or Enter to search {name}")
        self.search.setToolTip("Type to filter this artist's releases.\n"
                               f"Press Enter to search all of {name} (Ctrl+Shift+F).")
        self._update_search_btn()

    def set_palette(self, pal):
        self._delegate.pal = pal
        self.view.viewport().update()

    def clear(self):
        """Forget the artist's releases (shown search results stay)."""
        self._artist_releases = []
        if not self._searching:
            self._fill([])

    def set_releases(self, releases):
        """The current artist's releases."""
        self._artist_releases = list(releases)
        if not self._searching:
            self._fill(self._artist_releases)
            self._apply_filter()

    def end_search(self):
        """Back to the artist's releases with an empty box (new album)."""
        if self.search.text():
            self.search.clear()             # → _on_text restores the list
        elif self._searching:
            self._show_artist()

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def search_started(self, query):
        self._search_btn.setEnabled(False)
        self._search_btn.setText(f"Searching {self._source}…")

    def show_search_results(self, query, results, error=None):
        if query != self.search.text().strip():
            return                           # box changed while searching
        self._searching = True
        self._fill(results)
        self._search_btn.hide()
        self._back_btn.show()
        if error:
            self._hint.setText(f"Search failed: {error}")
        elif results:
            self._hint.setText(f"{self._source} results for “{query}”. Click one to use it.")
        else:
            self._hint.setText(f"Nothing on {self._source} for “{query}”.")

    def missing_thumbs(self):
        """Ids in the shown list that have no artwork yet."""
        return [rid for rid in self._items if rid not in self._thumbs]

    def set_thumb(self, release_id, pixmap):
        if pixmap.isNull():
            return
        self._thumbs[release_id] = rounded(pixmap, THUMB, 6)
        it = self._items.get(release_id)
        if it is not None:
            it.setData(self._thumbs[release_id], THUMB_ROLE)

    def select(self, release_id):
        it = self._items.get(release_id)
        if it is None or self.view.isRowHidden(it.row()):
            self.view.clearSelection()
            return
        idx = it.index()
        self.view.setCurrentIndex(idx)
        self.view.scrollTo(idx, QAbstractItemView.PositionAtCenter)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _fill(self, releases):
        self._model.clear()
        self._items = {}
        for r in releases:
            it = QStandardItem()
            it.setData(r, RELEASE_ROLE)
            if r["id"] in self._thumbs:
                it.setData(self._thumbs[r["id"]], THUMB_ROLE)
            tip = f"{r['title']} ({r.get('year', '')})"
            if r.get("artist"):
                tip = f"{r['artist']} — {tip}"
            it.setToolTip(tip)
            self._model.appendRow(it)
            self._items[r["id"]] = it
        self._badge.setText(str(len(releases)))

    def _show_artist(self):
        self._searching = False
        self._back_btn.hide()
        self._fill(self._artist_releases)
        self._apply_filter()

    def _on_text(self, text):
        if self._searching:
            if text.strip():
                # Editing a finished search: offer to run the new one.
                self._update_search_btn()
                return
            self._show_artist()
            return
        self._apply_filter()

    def _apply_filter(self):
        words = self.search.text().lower().split()
        shown = 0
        for row in range(self._model.rowCount()):
            rel = self._model.item(row).data(RELEASE_ROLE)
            hay = f"{rel['title']} {rel.get('year', '')} {rel.get('type', '')}".lower()
            hide = any(w not in hay for w in words)
            self.view.setRowHidden(row, hide)
            shown += not hide
        total = self._model.rowCount()
        self._badge.setText(f"{shown} / {total}" if words else str(total))
        if not words:
            self._hint.setText("Click a release to use it for this album.")
        elif shown:
            self._hint.setText(f"Not here? Press Enter to search all of {self._source}.")
        else:
            self._hint.setText("No match in this artist's releases.")
        self._update_search_btn()

    def _update_search_btn(self):
        q = self.search.text().strip()
        self._search_btn.setVisible(bool(q))
        self._search_btn.setEnabled(True)
        if q:
            self._search_btn.setText(
                self.fontMetrics().elidedText(f"Search {self._source} for “{q}”",
                                              Qt.ElideMiddle, 240))

    def _request_search(self):
        q = self.search.text().strip()
        if q:
            self.search_requested.emit(q)
