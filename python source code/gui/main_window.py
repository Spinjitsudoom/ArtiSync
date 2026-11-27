"""
gui/main_window.py
Main window: wires the panels to the session core.

  ┌ Top bar: title · music folder · Spotify status · Settings ─────────────┐
  │ Library │ Releases │ Album (tracks / log)              │ Details       │
  └ Action bar: progress · Update · Undo · Convert · Refresh · Prev/Next · Rename ┘

All Spotify and disk work runs off the GUI thread (gui.widgets.run_async).
Every album load gets a token; results for an album the user has already
left are dropped.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QSettings, QStorageInfo, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

import session
import updater
from version import VERSION
from base_engine import list_audio_files
from gui.album_view import AlbumView
from gui.details_panel import DetailsPanel
from gui.dialogs import ConvertDialog, SettingsDialog
from gui.update_dialog import UpdateDialog
from gui.library_panel import LibraryPanel
from gui.releases_panel import ReleasesPanel
from gui.theme import palette, stylesheet
from gui.widgets import Toast, folder_icon, run_async, set_prop
from remux_engine import RemuxEngine
from deezer_engine import DeezerEngine
from mb_engine import MusicBrainzEngine
from spotify_engine import SpotifyEngine


_NETWORK_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "fuse.sshfs", "sshfs",
               "davfs", "fuse.rclone", "9p", "afpfs"}
_DRIVE_ROOTS = ("/mnt/", "/var/mnt/", "/media/", "/run/media/", "/Volumes/")


def _places():
    """Folders for the folder picker's sidebar: home, Music, then every
    mounted drive and network share (including not-yet-mounted automounts)."""
    home = os.path.expanduser("~")
    places = [home]
    music = os.path.join(home, "Music")
    if os.path.isdir(music):
        places.append(music)

    found = []
    for vol in QStorageInfo.mountedVolumes():
        root = vol.rootPath()
        fs = bytes(vol.fileSystemType()).decode(errors="replace")
        if os.name == "nt":
            ok = vol.isValid() and vol.isReady()
        else:
            ok = (fs in _NETWORK_FS or root.startswith(_DRIVE_ROOTS)) \
                and vol.isValid() and vol.isReady()
        if ok and not root.startswith("/tmp/"):
            found.append(root)

    # systemd automounts (x-systemd.automount) appear as 'autofs' until first
    # access, and QStorageInfo skips them — read them from /proc/mounts.
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 2 and parts[2] == "autofs":
                    target = parts[1].replace("\\040", " ")
                    if target.startswith(_DRIVE_ROOTS):
                        found.append(target)
    except OSError:
        pass

    for p in sorted(set(found), key=str.casefold):
        if p not in places:
            places.append(p)
    return places


def _button(text, variant=None, tip=None, slot=None):
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


# Sources that need no account, by AppConfig.metadata_source value.
OPEN_SOURCES = {"deezer": DeezerEngine, "musicbrainz": MusicBrainzEngine}


class MainWindow(QMainWindow):

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.engine = SpotifyEngine()
        self.engine.track_number_prefix = cfg.track_numbers
        self.resolver = session.ReleaseResolver(self.engine)
        self.remux = RemuxEngine()
        self.store = session.StatusStore()
        self.pal = palette(cfg.theme)

        self.album = None          # AlbumFolder currently open
        self.release = None        # its release on the current source
        self.preview = None        # session.AlbumPreview
        self.undo_record = None
        self._undo_target = None   # (album, preview) the undo record belongs to
        self._token = 0
        self._busy = False
        # Requests that arrive while busy run once it's free (_run_pending).
        self._pending_album = None
        self._refresh_again = False
        self._releases_for = None  # artist folder whose releases are listed
        self._thumb_gen = 0        # bumped whenever the releases list changes
        self._update = None        # updater.Release newer than this copy

        self.setWindowTitle(f"ArtiSync {VERSION}")
        self.resize(1480, 920)
        self.setMinimumSize(1100, 680)
        self._build()
        self._shortcuts()
        self.apply_theme(cfg.theme)

        st = QSettings("ArtiSync", "ArtiSync")
        if st.value("geometry"):
            self.restoreGeometry(st.value("geometry"))
        if st.value("splitter"):
            self.splitter.restoreState(st.value("splitter"))

        QTimer.singleShot(0, self._startup)
        QTimer.singleShot(3000, self._auto_check_updates)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Top bar
        top = QFrame()
        top.setObjectName("TopBar")
        th = QHBoxLayout(top)
        th.setContentsMargins(16, 10, 12, 10)
        th.setSpacing(12)
        logo = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ArtiSync.png")
        pm = QPixmap(icon_path)
        if not pm.isNull():
            logo.setPixmap(pm.scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        th.addWidget(logo)
        title = QLabel("ArtiSync")
        title.setObjectName("AppTitle")
        th.addWidget(title)
        th.addSpacing(10)
        self.path_btn = _button("", tip="Choose your music folder (Ctrl+O)",
                                slot=self.choose_folder)
        self.path_btn.setObjectName("PathButton")
        self.path_btn.setMinimumWidth(320)
        th.addWidget(self.path_btn, 1)
        th.addStretch()
        self.spotify_pill = QLabel("Spotify")
        self.spotify_pill.setObjectName("SpotifyPill")
        th.addWidget(self.spotify_pill)
        th.addWidget(_button("Settings", "ghost", "Settings (Ctrl+,)", self.open_settings))
        v.addWidget(top)

        # Body
        self.library = LibraryPanel(self.pal)
        self.releases = ReleasesPanel(self.pal)
        self.album_view = AlbumView()
        self.details = DetailsPanel(self.pal, self.cfg.apply_art,
                                    self.cfg.apply_tags, self.cfg.apply_genre,
                                    self.cfg.track_numbers)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        for w, min_w in ((self.library, 220), (self.releases, 240),
                         (self.album_view, 420), (self.details, 240)):
            w.setMinimumWidth(min_w)
            self.splitter.addWidget(w)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([280, 300, 600, 300])
        v.addWidget(self.splitter, 1)

        # Action bar
        bar = QFrame()
        bar.setObjectName("ActionBar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(16, 10, 16, 10)
        bh.setSpacing(8)
        prog = QVBoxLayout()
        prog.setSpacing(5)
        self.progress_text = QLabel("No album open")
        self.progress_text.setObjectName("ProgressText")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(320)
        prog.addWidget(self.progress_text)
        prog.addWidget(self.progress)
        bh.addLayout(prog)
        bh.addStretch()
        self.update_btn = _button("Update available", "ghost",
                                  "A newer version of ArtiSync is available",
                                  self.show_update)
        self.update_btn.hide()
        bh.addWidget(self.update_btn)
        self.undo_btn = _button("Undo", "ghost", "Undo the last rename (Ctrl+Z)", self.undo)
        self.convert_btn = _button("Convert…", "ghost", "Convert files with FFmpeg",
                                   self.convert)
        self.refresh_btn = _button("Refresh", "ghost", "Re-read the album folder (F5)",
                                   self.refresh)
        self.prev_btn = _button("◀  Previous", tip="Previous album (Ctrl+←)",
                                slot=lambda: self.library.step(-1))
        self.next_btn = _button("Next album  ▶", tip="Next album (Ctrl+→)",
                                slot=lambda: self.library.step(+1))
        self.exec_btn = _button("Rename && Tag", "primary",
                                "Rename and tag the matched files (Ctrl+Enter)",
                                self.execute)
        for b in (self.undo_btn, self.convert_btn, self.refresh_btn):
            bh.addWidget(b)
        sep = QFrame()
        sep.setFixedSize(1, 24)
        sep.setStyleSheet("background: rgba(127,127,127,0.25);")
        bh.addSpacing(6)
        bh.addWidget(sep)
        bh.addSpacing(6)
        for b in (self.prev_btn, self.next_btn, self.exec_btn):
            bh.addWidget(b)
        v.addWidget(bar)

        self.setCentralWidget(root)
        self.toast = Toast(root, above=bar)

        # Signals
        self.library.album_selected.connect(self.open_album)
        self.releases.release_chosen.connect(self.choose_release)
        self.releases.search_requested.connect(self.search_releases)
        self.album_view.assign_requested.connect(self._assign)
        self.album_view.unassign_requested.connect(self._unassign)
        self.details.options_changed.connect(self._options_changed)
        self.details.reload_art.connect(self._reload_art)
        self.details.numbering_changed.connect(self._numbering_changed)
        self._update_actions()

    def _shortcuts(self):
        for keys, fn in (("Ctrl+Right", lambda: self.library.step(+1)),
                         ("Ctrl+Left", lambda: self.library.step(-1)),
                         ("Ctrl+Return", self.execute), ("Ctrl+Enter", self.execute),
                         ("Ctrl+Z", self.undo), ("F5", self.refresh),
                         ("Ctrl+F", lambda: self.library.filter.setFocus()),
                         ("Ctrl+Shift+F", self.releases.focus_search),
                         ("Ctrl+,", self.open_settings), ("Ctrl+O", self.choose_folder)):
            QShortcut(QKeySequence(keys), self, activated=fn)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.toast.reposition()

    def closeEvent(self, e):
        if self._busy:
            # The app exits with os._exit() shortly after the window closes;
            # quitting mid-rename would strand files under temporary names.
            QMessageBox.information(self, "Please wait",
                                    "ArtiSync is still renaming or tagging files. "
                                    "Close it once that has finished.")
            e.ignore()
            return
        self._releases_for = None
        self._thumb_gen += 1               # stops the thumbnail loader
        getattr(self.engine, "close", lambda: None)()   # and queued lookups
        st = QSettings("ArtiSync", "ArtiSync")
        st.setValue("geometry", self.saveGeometry())
        st.setValue("splitter", self.splitter.saveState())
        st.sync()                          # written now: the app exits without cleanup
        super().closeEvent(e)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def apply_theme(self, name):
        self.pal = p = palette(name)
        app = QApplication.instance()
        qp = QPalette()
        for role, key in ((QPalette.Window, "window"), (QPalette.WindowText, "text"),
                          (QPalette.Base, "card"), (QPalette.AlternateBase, "panel"),
                          (QPalette.Text, "text"), (QPalette.Button, "raised"),
                          (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection"),
                          (QPalette.HighlightedText, "selection_text"),
                          (QPalette.ToolTipBase, "raised"), (QPalette.ToolTipText, "text"),
                          (QPalette.PlaceholderText, "faint"), (QPalette.Link, "accent"),
                          (QPalette.Mid, "border"), (QPalette.Dark, "border")):
            qp.setColor(role, QColor(p[key]))
        qp.setColor(QPalette.Disabled, QPalette.Text, QColor(p["faint"]))
        qp.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["faint"]))
        app.setPalette(qp)
        app.setStyleSheet(stylesheet(name))
        self.library.set_palette(p)
        self.path_btn.setIcon(folder_icon(p["muted"]))
        self.releases.set_palette(p)
        self.details.art.set_palette(p)

    # ── Startup / library ─────────────────────────────────────────────────────

    def _startup(self):
        if self.cfg.metadata_source in OPEN_SOURCES:
            self._set_engine(OPEN_SOURCES[self.cfg.metadata_source]())
            self.load_library()
        elif self.cfg.spotify_id and self.cfg.spotify_secret:
            self._set_pill("Connecting to Spotify…", None)
            cid, sec = self.cfg.spotify_id, self.cfg.spotify_secret

            def done(engine, err):
                if engine is not None and engine.is_configured:
                    self._set_engine(engine)
                else:
                    self._set_pill("Spotify: can't connect", "bad")
                self.load_library()

            run_async(lambda: SpotifyEngine(cid, sec), done)
        else:
            self._set_pill("Spotify not set up", "bad")
            self.load_library()

    def _set_engine(self, engine):
        if engine is not self.engine:
            getattr(self.engine, "close", lambda: None)()
        engine.track_number_prefix = self.cfg.track_numbers
        self.engine = engine
        self.resolver = session.ReleaseResolver(engine)
        self._releases_for = None
        self.releases.end_search()
        self.releases.clear()
        self.releases.set_source(engine.name)
        if engine.name != "Spotify":
            self._set_pill(f"●  {engine.name}", "ok")
        elif getattr(engine, "rate_limited_seconds", lambda: 0)():
            self._set_pill("Spotify: rate-limited", "bad")
        elif engine.is_configured:
            self._set_pill("●  Spotify connected", "ok")
        else:
            self._set_pill("Spotify not set up", "bad")

    def _set_pill(self, text, state):
        self.spotify_pill.setText(text)
        set_prop(self.spotify_pill, "state", state or "")

    def load_library(self):
        root = self.cfg.path
        self.path_btn.setText(root or "Choose your music folder…")
        artists = session.scan_library(root)
        self.library.set_library(artists, lambda a: self.store.status(root, a))
        if not root or not os.path.isdir(root):
            self.album_view.set_heading("Welcome to ArtiSync")
            self.album_view.show_message(
                "Choose the folder that holds your artist folders to get started.",
                "Choose music folder", self.choose_folder)
            return
        if not self.library.albums:
            self.album_view.set_heading(os.path.basename(root))
            self.album_view.show_message(
                "No album folders found here.\nArtiSync expects Artist / Album / tracks.")
            return
        first = self.library.first_unfinished()
        if first:
            self.library.select(first)

    def choose_folder(self):
        dlg = QFileDialog(self, "Choose music folder",
                          self.cfg.path or os.path.expanduser("~"))
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        # Qt's own dialog (the pip build of PySide6 has no desktop
        # integration) only lists home in its sidebar; add every drive and
        # network share so they can be reached without typing a path.
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setSidebarUrls([QUrl.fromLocalFile(p) for p in _places()])
        if dlg.exec() and dlg.selectedFiles():
            self.cfg.path = dlg.selectedFiles()[0]
            self.cfg.save()
            self.load_library()

    # ── Opening an album ──────────────────────────────────────────────────────

    def open_album(self, album):
        if self._busy:
            self._pending_album = album        # opened when the work finishes
            return
        self._token += 1
        tok = self._token
        if self.album is None or album.key != self.album.key:
            self.releases.end_search()
        self.album, self.release, self.preview = album, None, None
        self.album_view.set_heading(album.name, album.artist)
        self.album_view.show_message("Loading…")
        self.details.clear()
        self._update_actions()

        if not self.engine.is_configured:
            self.album_view.show_message(
                "Connect Spotify to match this album, or switch to Deezer or "
                "MusicBrainz in Settings (no account needed).", "Open Settings",
                self.open_settings)
            return

        resolver, engine = self.resolver, self.engine
        override = self.store.release_override(self.cfg.path, album, self.engine.name)

        def work():
            am = resolver.artist(album.artist)
            rel = None
            if override:
                # A release picked by hand, possibly from a search
                # and so not among the folder artist's releases.
                rel = next((r for r in am.releases if r["id"] == override), None) \
                    if am else None
                rel = rel or engine.get_release(override)
            if rel is None and am is not None:
                rel = resolver.match_release(am, album.name)
            if rel is None:
                return am, None, None
            tracks = engine.get_tracks(rel["id"])
            return am, rel, session.AlbumPreview(album.path, rel, tracks, engine)

        run_async(work, lambda res, err: self._album_loaded(tok, album, res, err))

    def _album_loaded(self, tok, album, res, err):
        if tok != self._token:
            return
        failed = err is not None or res[0] is None or res[1] is None
        if failed and self._show_rate_limit():
            return
        if err is not None:
            self.album_view.show_message(f"Couldn't load this album.\n\n{err}")
            return
        am, rel, pv = res
        if am is None:
            self.releases.clear()
            self._releases_for = None
            if rel is None:
                self.album_view.show_message(
                    f"Couldn't find “{album.artist}” on {self.engine.name}.\n"
                    "Search for the album in Releases (Ctrl+Shift+F).",
                    "Search", lambda: self._search_for_album(album))
                return
        else:
            self._show_releases(album.artist, am)
        if rel is None:
            self.releases.select(None)
            self.album_view.show_message(
                "Couldn't match this folder to a release.\n"
                f"Pick the right one from Releases, or search {self.engine.name}.",
                "Search", lambda: self._search_for_album(album))
            return
        self.release, self.preview = rel, pv
        self.releases.select(rel["id"])
        artist_name = am.name if am else rel.get("artist", album.artist)
        self.album_view.set_heading(
            album.name,
            f"{artist_name}   ·   {self.engine.name}: {rel['title']} ({rel.get('year', '')})"
            f"   ·   {len(pv.tracks)} tracks")
        if not pv.tracks:
            self.album_view.show_message(
                f"{self.engine.name} returned no tracks for this release.")
            return
        self._render()
        self._load_details(tok, rel)
        self._prefetch(self.library.next_after(album))

    def _render(self):
        pv = self.preview
        self.album_view.show_preview(pv)
        st = pv.status
        self.store.set_status(self.cfg.path, self.album, st)
        self.library.set_status(self.album, st)
        self._update_actions()

    def _update_actions(self):
        pv = self.preview
        if pv is None:
            self.progress_text.setText("No album open" if self.album is None else "Loading…")
            self.progress.setValue(0)
        else:
            n, m = len(pv.rows), len(pv.matched)
            self.progress.setRange(0, max(n, 1))
            self.progress.setValue(m)
            extra = f"   ·   {len(pv.pending)} to rename" if pv.pending else ""
            self.progress_text.setText(f"{m} / {n} tracks matched{extra}")
        ready = pv is not None and bool(pv.matched) and not self._busy
        self.exec_btn.setEnabled(ready)
        self.convert_btn.setEnabled(self.album is not None and not self._busy)
        self.refresh_btn.setEnabled(pv is not None and not self._busy)
        self.undo_btn.setEnabled(bool(self.undo_record) and not self._busy)
        self.album_view.setEnabled(not self._busy)

    def _show_releases(self, artist_folder, am):
        if self._releases_for == artist_folder:
            if not self.releases.searching:
                self._load_thumbs()        # resume after a search interrupted it
            return
        self._releases_for = artist_folder
        self.releases.set_releases(am.releases)
        self._load_thumbs()

    def _load_thumbs(self):
        """Fetch artwork for whatever the releases list shows, one at a time,
        stopping as soon as the list is replaced."""
        self._thumb_gen += 1
        gen, engine, ids = self._thumb_gen, self.engine, self.releases.missing_thumbs()
        if not ids:
            return
        thumbs = {}

        fetch = getattr(engine, "get_thumbnail_bytes", engine.get_cover_art_bytes)

        def one(rid):
            if self._thumb_gen != gen:
                return rid
            try:
                thumbs[rid] = fetch(rid)
            except Exception:
                thumbs[rid] = None
            return rid

        def work(report):
            # A few at a time: cover art servers are slow per image, not
            # rate-limited.
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(one, rid) for rid in ids]
                for i, fut in enumerate(as_completed(futures)):
                    if self._thumb_gen != gen:
                        for f in futures:
                            f.cancel()
                        return
                    report(i, len(ids), fut.result())

        def got(_i, _n, rid):
            data = thumbs.get(rid)
            if data and self._thumb_gen == gen:
                pm = QPixmap()
                pm.loadFromData(data)
                self.releases.set_thumb(rid, pm)

        run_async(work, None, got)

    def search_releases(self, query):
        """Album search across the whole source, from the releases search box."""
        if not self.engine.is_configured:
            self.releases.show_search_results(query, [], "Spotify isn't connected.")
            return
        self.releases.search_started(query)
        engine = self.engine

        def done(res, err):
            limited = getattr(engine, "rate_limit_message", lambda: None)()
            if err and limited:
                err = limited
            self.releases.show_search_results(query, res or [],
                                              str(err) if err else None)
            if self.release:
                self.releases.select(self.release["id"])
            self._load_thumbs()

        run_async(lambda: engine.search_releases(query), done)

    def _show_rate_limit(self):
        """If the source is refusing requests, say so (with a way out) and
        return True."""
        msg = getattr(self.engine, "rate_limit_message", lambda: None)()
        if not msg:
            return False
        self._set_pill("Spotify: rate-limited", "bad")
        self.album_view.show_message(
            f"{msg}\nSwitch to Deezer to keep working, or try again later.",
            "Use Deezer", lambda: self._switch_source("deezer"))
        return True

    def _switch_source(self, source):
        self.cfg.metadata_source = source
        self.cfg.save()
        self._set_engine(OPEN_SOURCES[source]())
        if self.album:
            self.open_album(self.album)

    def _search_for_album(self, album):
        """Prefill the search box with the folder's artist and album."""
        title = session._YEAR_SUFFIX.sub("", album.name).strip() or album.name
        q = f"{album.artist} {title}"
        self.releases.search.setText(q)
        self.releases.focus_search()
        self.search_releases(q)

    def _load_details(self, tok, rel):
        engine = self.engine

        def done(res, err):
            if tok != self._token or err is not None:
                return
            meta, art = res
            self.details.set_metadata(meta)
            pm = QPixmap()
            if art:
                pm.loadFromData(art)
            self.details.art.set_pixmap(pm if not pm.isNull() else None,
                                        "" if art else "No artwork")

        run_async(lambda: (engine.get_release_metadata(rel["id"]),
                           engine.get_cover_art_bytes(rel["id"])), done)

    def _prefetch(self, album):
        """Warm the caches for the next album so moving forward is instant."""
        if album is None:
            return
        resolver, engine = self.resolver, self.engine
        override = self.store.release_override(self.cfg.path, album, self.engine.name)

        def work():
            am = resolver.artist(album.artist)
            rel = am and (next((r for r in am.releases if r["id"] == override), None)
                          or resolver.match_release(am, album.name))
            if rel:
                engine.get_tracks(rel["id"])
                engine.get_release_metadata(rel["id"])
                engine.get_cover_art_bytes(rel["id"])

        run_async(work)

    def choose_release(self, rel):
        if self.album is None or self._busy or rel is None:
            return
        if self.release and rel["id"] == self.release["id"]:
            return
        self.store.set_release_override(self.cfg.path, self.album, rel["id"],
                                       self.engine.name)
        self.open_album(self.album)

    def _reload_art(self):
        if not self.release:
            return
        getattr(self.engine, "_art_cache", {}).pop(self.release["id"], None)
        self._load_details(self._token, self.release)

    def _numbering_changed(self, on):
        self.cfg.track_numbers = on
        self.cfg.save()
        self.engine.track_number_prefix = on
        self.refresh()                      # re-propose names for the open album

    def _options_changed(self, art, tags, genre):
        self.cfg.apply_art, self.cfg.apply_tags, self.cfg.apply_genre = art, tags, genre
        self.cfg.save()

    # ── Pairing ───────────────────────────────────────────────────────────────

    # These come from a row's popup menu. Re-rendering deletes that row (and
    # its menu), so wait until the menu has closed and returned.

    def _assign(self, row_key, filename):
        QTimer.singleShot(0, lambda: self._apply_pairing(
            lambda pv: pv.assign(row_key, filename)))

    def _unassign(self, row_key):
        QTimer.singleShot(0, lambda: self._apply_pairing(
            lambda pv: pv.unassign(row_key)))

    def _apply_pairing(self, change):
        if self.preview and not self._busy:
            change(self.preview)
            self._render()

    def refresh(self):
        if self.preview is None:
            return
        if self._busy:
            self._refresh_again = True         # e.g. numbering toggled mid-rename
            return
        pv, tok = self.preview, self._token
        # Busy while the worker rewrites pv's rows, so Execute and manual
        # pairing can't read or edit them half-updated.
        self._set_busy(True)

        def done(_r, err):
            if tok == self._token and err is None:
                self._render()
            self._set_busy(False)

        run_async(pv.refresh, done)

    # ── Execute / undo / convert ──────────────────────────────────────────────

    def _set_busy(self, busy, text=None):
        self._busy = busy
        self._update_actions()
        if text:
            self.progress_text.setText(text)
        if not busy and (self._pending_album or self._refresh_again):
            # After the caller's own completion handling has run.
            QTimer.singleShot(0, self._run_pending)

    def _run_pending(self):
        if self._busy:
            return
        album, self._pending_album = self._pending_album, None
        if album is not None:
            self._refresh_again = False        # opening re-reads the folder anyway
            self.open_album(album)
        elif self._refresh_again:
            self._refresh_again = False
            self.refresh()

    def execute(self):
        pv, rel, album, tok = self.preview, self.release, self.album, self._token
        if pv is None or self._busy or not pv.matched:
            return
        loose = pv.unmatched_files
        if loose:
            ans = QMessageBox.question(
                self, "Some files aren't matched",
                f"{len(loose)} file{'s' * (len(loose) != 1)} in this folder "
                f"{'aren' if len(loose) != 1 else 'isn'}'t matched to a track and "
                f"will be left as {'they are' if len(loose) != 1 else 'it is'}.\n\n"
                f"Rename and tag the other {len(pv.matched)}?")
            if ans != QMessageBox.Yes:
                return
        c = self.cfg
        opts = session.ExecuteOptions(c.apply_art, c.apply_tags, c.apply_genre,
                                      c.auto_remux and self.remux.is_available,
                                      c.auto_remux_target, c.auto_remux_quality,
                                      c.auto_remux_delete_source)
        engine, remux = self.engine, self.remux
        self._set_busy(True, "Renaming and tagging…")

        def work():
            meta = engine.get_release_metadata(rel["id"])
            art = engine.get_cover_art_bytes(rel["id"]) if opts.apply_art else None
            result = session.execute(pv, meta, art, opts, remux)
            pv.refresh()
            return result

        def done(result, err):
            self._set_busy(False)
            if err is not None:
                QMessageBox.critical(self, "Rename failed", str(err))
                return
            if result.undo:
                self.undo_record, self._undo_target = result.undo, (album, pv)
            self._after_change(album, pv, tok)
            bits = [f"Renamed {result.renamed}", f"tagged {result.tagged}"]
            if result.converted:
                bits.append(f"converted {result.converted}")
            self.toast.show_message("  ·  ".join(bits),
                                    "Undo" if result.undo else None, self.undo)
            if result.warnings:
                self._warn("Some files were skipped", result.warnings)

        run_async(work, done)

    def undo(self):
        if not self.undo_record or self._busy:
            if not self.undo_record:
                self.toast.show_message("Nothing to undo", ms=2500)
            return
        record, (album, pv) = self.undo_record, self._undo_target
        tok = self._token
        self._set_busy(True, "Undoing…")

        def work():
            out = session.undo(record)
            pv.refresh()
            return out

        def done(out, err):
            self._set_busy(False)
            if err is not None:
                QMessageBox.critical(self, "Undo failed", str(err))
                return
            self.undo_record = self._undo_target = None
            self._after_change(album, pv, tok)
            msg = f"Reverted {out.reverted} rename{'s' * (out.reverted != 1)}"
            if out.removed:
                msg += f"  ·  removed {out.removed} converted"
            self.toast.show_message(msg)
            problems = list(out.errors)
            if out.unrecoverable:
                problems.insert(0, f"{out.unrecoverable} converted file(s) can't be "
                                   "restored — their originals were deleted.")
            if problems:
                self._warn("Undo couldn't restore everything", problems)
            self._update_actions()

        run_async(work, done)

    def _after_change(self, album, pv, tok):
        """Re-render if the changed album is still open; otherwise just update
        its status in the library."""
        if tok == self._token and self.preview is pv:
            self._render()
        else:
            st = pv.status
            self.store.set_status(self.cfg.path, album, st)
            self.library.set_status(album, st)
            self._update_actions()

    def convert(self):
        if self.album is None or self._busy:
            return
        if not self.remux.is_available:
            QMessageBox.warning(self, "FFmpeg not found",
                                "Converting needs FFmpeg. Install it and make sure "
                                "it's on your PATH, then restart ArtiSync.")
            return
        files = sorted(list_audio_files(self.album.path), key=str.casefold)
        if not files:
            self.toast.show_message("No audio files in this folder", ms=3000)
            return
        dlg = ConvertDialog(self.album.path, files, self.remux, self)
        dlg.exec()
        if dlg.converted:
            self.toast.show_message(f"Converted {dlg.converted} file{'s' * (dlg.converted != 1)}")
            self.refresh()

    # ── Settings ──────────────────────────────────────────────────────────────

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        dlg.theme_previewed.connect(self.apply_theme)
        dlg.update_found.connect(lambda rel: self._offer_update(rel, ask=True))
        if dlg.exec() != SettingsDialog.Accepted:
            return
        self.cfg.save()
        self.apply_theme(self.cfg.theme)
        new = None
        if self.cfg.metadata_source in OPEN_SOURCES:
            cls = OPEN_SOURCES[self.cfg.metadata_source]
            if not isinstance(self.engine, cls):
                new = cls()
        elif dlg.validated_engine is not None:
            new = dlg.validated_engine
        elif self.engine.name != "Spotify" or not (self.cfg.spotify_id and self.cfg.spotify_secret):
            if self.cfg.spotify_id and self.cfg.spotify_secret:
                # Connecting makes a network call; keep it off the GUI thread.
                cid, sec = self.cfg.spotify_id, self.cfg.spotify_secret
                self._set_pill("Connecting to Spotify…", None)

                def connected(engine, err):
                    self._set_engine(engine if engine is not None else SpotifyEngine())
                    if self.album:
                        self.open_album(self.album)

                run_async(lambda: SpotifyEngine(cid, sec), connected)
                return
            new = SpotifyEngine()
        if new is not None:
            self._set_engine(new)
            if self.album:
                self.open_album(self.album)

    # ── Updates ───────────────────────────────────────────────────────────────

    def _auto_check_updates(self):
        if self.cfg.check_updates:
            run_async(updater.check, self._update_checked)

    def _update_checked(self, rel, err):
        # Failures are silent here; Settings → Check now reports them.
        if err is None and rel is not None and rel.version != self.cfg.skip_version:
            self._offer_update(rel)

    def _offer_update(self, rel, ask=False):
        self._update = rel
        self.update_btn.setText(f"Update to {rel.version}")
        self.update_btn.show()
        if ask:
            self.show_update()
        else:
            self.toast.show_message(f"ArtiSync {rel.version} is available",
                                    "Update…", self.show_update, ms=12000)

    def show_update(self):
        if self._update is None:
            return
        parent = QApplication.activeModalWidget() or self
        dlg = UpdateDialog(self._update, lambda: not self._busy, parent)
        dlg.exec()
        if dlg.skipped:
            self.cfg.skip_version = self._update.version
            self.cfg.save()
            self.update_btn.hide()
        if dlg.restart:
            # The update finishes (and reopens ArtiSync) once this copy exits.
            QTimer.singleShot(0, QApplication.instance().closeAllWindows)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _warn(self, title, lines):
        box = QMessageBox(QMessageBox.Warning, title,
                          f"{len(lines)} item{'s' * (len(lines) != 1)} need your attention.",
                          QMessageBox.Ok, self)
        box.setDetailedText("\n".join(lines))
        box.exec()
