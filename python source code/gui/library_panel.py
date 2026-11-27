"""
gui/library_panel.py
Left column: every artist folder with its album folders, a status mark per
album, a done counter and a filter box.
"""

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QTreeView, QVBoxLayout,
                               QWidget)

from session import DONE

ALBUM_ROLE = Qt.UserRole + 1


class LibraryPanel(QWidget):
    album_selected = Signal(object)          # AlbumFolder

    def __init__(self, pal, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._pal = pal
        self._albums = []                    # AlbumFolder in display order
        self._items = {}                     # album key → QStandardItem
        self._artist_items = {}              # artist name → (name item, count item)
        self._status = {}                    # album key → status
        self._icons = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 6, 8)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        title = QLabel("LIBRARY")
        title.setObjectName("PanelHeader")
        self._badge = QLabel("0 / 0 done")
        self._badge.setObjectName("Badge")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._badge)
        lay.addLayout(head)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter artists & albums")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)

        self._model = QStandardItemModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)
        self.filter.textChanged.connect(self._on_filter)

        self.tree = QTreeView()
        self.tree.setObjectName("LibraryTree")
        self.tree.setModel(self._proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setAnimated(True)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        lay.addWidget(self.tree, 1)

        self.tree.selectionModel().currentChanged.connect(self._on_current)
        self._debounce = QTimer(self, singleShot=True, interval=180,
                                timeout=self._emit_current)

    # ── Population ────────────────────────────────────────────────────────────

    def set_library(self, artists, status_of):
        self._model.clear()
        self._albums, self._items, self._artist_items, self._status = [], {}, {}, {}
        for artist in artists:
            a_item = QStandardItem(artist.name)
            a_item.setSelectable(False)
            f = a_item.font()
            f.setBold(True)
            a_item.setFont(f)
            count = QStandardItem("")
            count.setSelectable(False)
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for album in artist.albums:
                it = QStandardItem(album.name)
                it.setData(album, ALBUM_ROLE)
                it.setToolTip(album.path)
                blank = QStandardItem("")
                a_item.appendRow([it, blank])
                self._albums.append(album)
                self._items[album.key] = it
                self._status[album.key] = status_of(album)
                self._paint(album.key)
            self._model.appendRow([a_item, count])
            self._artist_items[artist.name] = (a_item, count)
            self._paint_artist(artist.name)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._update_badge()

    def set_palette(self, pal):
        self._pal = pal
        self._icons.clear()
        for key in self._items:
            self._paint(key)

    def set_status(self, album, status):
        self._status[album.key] = status
        self._paint(album.key)
        self._paint_artist(album.artist)
        self._update_badge()

    def _icon(self, status):
        from gui.widgets import status_icon
        if status not in self._icons:
            self._icons[status] = status_icon(status, self._pal)
        return self._icons[status]

    def _paint(self, key):
        self._items[key].setIcon(self._icon(self._status.get(key)))

    def _paint_artist(self, artist):
        keys = [a.key for a in self._albums if a.artist == artist]
        done = sum(self._status.get(k) == DONE for k in keys)
        _, count = self._artist_items[artist]
        count.setText(f"{done}/{len(keys)}")

    def _update_badge(self):
        done = sum(s == DONE for s in self._status.values())
        self._badge.setText(f"{done} / {len(self._albums)} done")

    # ── Selection / navigation ────────────────────────────────────────────────

    @property
    def albums(self):
        return list(self._albums)

    def current_album(self):
        idx = self.tree.currentIndex()
        return idx.siblingAtColumn(0).data(ALBUM_ROLE) if idx.isValid() else None

    def select(self, album, emit=True):
        item = self._items.get(album.key)
        if not item:
            return
        idx = self._proxy.mapFromSource(item.index())
        if not idx.isValid():                 # hidden by the filter
            self.filter.clear()
            idx = self._proxy.mapFromSource(item.index())
        self.tree.expand(idx.parent())
        self._suppress = not emit
        self.tree.setCurrentIndex(idx)
        self._suppress = False
        self.tree.scrollTo(idx)

    def step(self, delta):
        """Select the next/previous album in library order."""
        if not self._albums:
            return
        cur = self.current_album()
        i = self._albums.index(cur) if cur in self._albums else -1
        j = max(0, min(len(self._albums) - 1, i + delta))
        if j != i:
            self.select(self._albums[j])

    def first_unfinished(self):
        return next((a for a in self._albums if self._status.get(a.key) != DONE),
                    self._albums[0] if self._albums else None)

    def next_after(self, album):
        try:
            return self._albums[self._albums.index(album) + 1]
        except (ValueError, IndexError):
            return None

    _suppress = False

    def _on_current(self, cur, _prev):
        if (self._suppress or not cur.isValid()
                or cur.siblingAtColumn(0).data(ALBUM_ROLE) is None):
            return
        self._debounce.start()

    def _emit_current(self):
        album = self.current_album()
        if album is not None:
            self.album_selected.emit(album)

    def _on_filter(self, text):
        self._proxy.setFilterFixedString(text)
        if text:
            self.tree.expandAll()
