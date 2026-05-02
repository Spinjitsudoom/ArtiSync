import os
import io
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import customtkinter as ctk

from spotify_engine import SpotifyEngine
from metadata_writer import write_metadata, write_metadata_batch
from remux_engine import RemuxEngine, SUPPORTED_OUTPUT, SUPPORTED_INPUT

try:
    from PIL import Image as PilImage
    _RESAMPLE = getattr(PilImage, "LANCZOS", None) or getattr(PilImage, "ANTIALIAS", None)
    PIL_AVAILABLE = True
    PIL_ERROR = None
except Exception as _pil_exc:
    PilImage = None
    _RESAMPLE = None
    PIL_AVAILABLE = False
    PIL_ERROR = str(_pil_exc)

THEMES = {
    "Dark":     {"bg": "#121212", "fg": "#e0e0e0", "btn": "#2d2d2d", "entry": "#1e1e1e", "accent": "#0078d4", "border": "#333333"},
    "Light":    {"bg": "#ffffff", "fg": "#202124", "btn": "#f1f3f4", "entry": "#f8f9fa", "accent": "#1a73e8", "border": "#dadce0"},
    "Midnight": {"bg": "#0b0e14", "fg": "#8f9bb3", "btn": "#1a212e", "entry": "#151a23", "accent": "#3366ff", "border": "#222b45"},
    "Emerald":  {"bg": "#061006", "fg": "#a3b3a3", "btn": "#102010", "entry": "#0b160b", "accent": "#009688", "border": "#1b301b"},
    "Amethyst": {"bg": "#120d1a", "fg": "#b3a3cc", "btn": "#1f162e", "entry": "#181223", "accent": "#9b59b6", "border": "#2d2245"},
    "Crimson":  {"bg": "#1a0a0a", "fg": "#d6b4b4", "btn": "#2e1616", "entry": "#241212", "accent": "#e74c3c", "border": "#452222"},
    "Forest":   {"bg": "#0d1a12", "fg": "#b4d6c1", "btn": "#162e1f", "entry": "#12241a", "accent": "#2ecc71", "border": "#22452d"},
    "Ocean":    {"bg": "#0a161a", "fg": "#b4ccd6", "btn": "#16282e", "entry": "#122024", "accent": "#3498db", "border": "#223a45"},
    "Slate":    {"bg": "#1c232b", "fg": "#cbd5e0", "btn": "#2d3748", "entry": "#242d38", "accent": "#a0aec0", "border": "#4a5568"},
}

def _ctk_btn(parent, text, command, c, width=None, **kw):
    kwargs = dict(text=text, command=command, fg_color=c["btn"], text_color=c["fg"],
                  hover_color=c["accent"], border_width=1, border_color=c["border"], corner_radius=4)
    if width: kwargs["width"] = width
    kwargs.update(kw)
    return ctk.CTkButton(parent, **kwargs)

def _ctk_entry(parent, c, textvariable=None, width=None, justify="left", **kw):
    kwargs = dict(fg_color=c["entry"], text_color=c["fg"], border_color=c["border"],
                  border_width=1, corner_radius=4)
    if textvariable: kwargs["textvariable"] = textvariable
    if width: kwargs["width"] = width
    if justify != "left": kwargs["justify"] = justify
    kwargs.update(kw)
    return ctk.CTkEntry(parent, **kwargs)

def _ctk_label(parent, text, c, font=None, anchor="w", **kw):
    kwargs = dict(text=text, text_color=c["fg"], fg_color="transparent", anchor=anchor)
    if font: kwargs["font"] = font
    kwargs.update(kw)
    return ctk.CTkLabel(parent, **kwargs)

def _ctk_combo(parent, c, values=None, command=None, width=160, **kw):
    kwargs = dict(values=values or [], fg_color=c["entry"], text_color=c["fg"],
                  button_color=c["btn"], button_hover_color=c["accent"],
                  dropdown_fg_color=c["entry"], dropdown_text_color=c["fg"],
                  dropdown_hover_color=c["accent"], border_color=c["border"],
                  border_width=1, corner_radius=4, width=width, state="readonly")
    if command: kwargs["command"] = command
    kwargs.update(kw)
    return ctk.CTkComboBox(parent, **kwargs)

def _ctk_scrollbar(parent, orient, command, c):
    return ctk.CTkScrollbar(parent, orientation=orient, command=command,
                            fg_color=c["bg"], button_color=c["btn"],
                            button_hover_color=c["accent"])


class MusicManagerApp:
    VERSION  = "v2.1.0"
    ART_SIZE = 200

    def __init__(self, root):
        self.root = root
        self.root.title(f"Music Manager Ultimate {self.VERSION}")
        self.root.geometry("1400x980")

        self.config_file = Path("music_config.json")
        self.spot_engine = SpotifyEngine()
        self.remux_engine = RemuxEngine()

        defaults = {"path": "", "theme": "Dark", "spotify_id": "", "spotify_secret": "",
                    "auto_remux": False, "auto_remux_target": ".flac",
                    "auto_remux_quality": "best", "auto_remux_delete_source": True}
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    defaults.update(json.load(f))
            except Exception:
                pass

        if defaults["spotify_id"] and defaults["spotify_secret"]:
            self.spot_engine.configure(defaults["spotify_id"], defaults["spotify_secret"])

        self.root_dir        = tk.StringVar(value=defaults["path"])
        self.current_theme   = tk.StringVar(value=defaults["theme"])
        self.apply_art       = tk.BooleanVar(value=True)
        self.apply_tags      = tk.BooleanVar(value=True)
        self.apply_genre     = tk.BooleanVar(value=True)
        self._spotify_id     = defaults["spotify_id"]
        self._spotify_secret = defaults["spotify_secret"]
        self._auto_remux        = defaults["auto_remux"]
        self._auto_remux_target = defaults["auto_remux_target"]
        self._auto_remux_quality  = defaults["auto_remux_quality"]
        self._auto_remux_del_src  = defaults["auto_remux_delete_source"]

        self.current_artist_id    = None
        self.current_release_id   = None
        self.current_tracks       = []
        self.current_metadata     = {}
        self.current_art_bytes    = None
        self._art_photo           = None
        self._art_ctk_image       = None
        self._known_releases      = []
        self._sidebar_rows        = []   # list of dicts per release row
        self._active_tab          = "Preview"
        self._preview_log         = ""
        self._log_text_full       = ""

        self.selected_artist_path = tk.StringVar()
        self.selected_album_path  = tk.StringVar()
        self.episodes_data        = []
        self.batch_data           = []
        self.rename_history       = []

        # Theme-update registries
        self._reg_labels     = []
        self._reg_buttons    = []
        self._reg_btn_accent = []
        self._reg_entries    = []
        self._reg_combos     = []
        self._reg_tk_frames  = []
        self._reg_separators = []
        self._reg_scrollbars = []

        c = THEMES.get(defaults["theme"], THEMES["Dark"])
        ctk.set_appearance_mode("light" if defaults["theme"] == "Light" else "dark")
        self.root.configure(bg=c["bg"])

        self.create_widgets(c)
        self.create_menu(c)

        if not PIL_AVAILABLE:
            detail = f"\n\nError: {PIL_ERROR}" if PIL_ERROR else ""
            messagebox.showwarning("Pillow not available",
                f"Artwork previews need Pillow.\n\nRun: pip install Pillow{detail}")

        if os.path.exists(self.root_dir.get()):
            self.refresh_artists()

    @property
    def engine(self):
        return self.spot_engine

    # ── Menu ──────────────────────────────────────────────────────────────────

    def create_menu(self, c):
        self.menubar   = tk.Menu(self.root)
        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="Settings…", command=self._open_settings)
        theme_menu = tk.Menu(self.file_menu, tearoff=0)
        for t in THEMES:
            theme_menu.add_command(label=t, command=lambda n=t: self._switch_theme(n))
        self.file_menu.add_cascade(label="Theme", menu=theme_menu)
        self.file_menu.add_command(label="Undo Last Rename", command=self.undo_rename)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.root.quit)
        self.root.config(menu=self.menubar)
        self._paint_menu(c)

    def _paint_menu(self, c):
        self.menubar.configure(bg=c["bg"], fg=c["fg"])
        self.file_menu.configure(bg=c["bg"], fg=c["fg"], activebackground=c["accent"])

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _switch_theme(self, name):
        self.current_theme.set(name)
        c = THEMES.get(name, THEMES["Dark"])
        ctk.set_appearance_mode("light" if name == "Light" else "dark")

        self.root.configure(bg=c["bg"])
        for w in self._reg_tk_frames:
            try: w.configure(bg=c["bg"])
            except Exception: pass
        for w, _ in self._reg_labels:
            try: w.configure(text_color=c["fg"])
            except Exception: pass
        for w in self._reg_buttons:
            try: w.configure(fg_color=c["btn"], text_color=c["fg"],
                             hover_color=c["accent"], border_color=c["border"])
            except Exception: pass
        for w in self._reg_entries:
            try: w.configure(fg_color=c["entry"], text_color=c["fg"],
                             border_color=c["border"])
            except Exception: pass
        for w in self._reg_combos:
            try: w.configure(fg_color=c["entry"], text_color=c["fg"],
                             button_color=c["btn"], button_hover_color=c["accent"],
                             dropdown_fg_color=c["entry"], dropdown_text_color=c["fg"],
                             dropdown_hover_color=c["accent"], border_color=c["border"])
            except Exception: pass
        for w in self._reg_btn_accent:
            try: w.configure(fg_color=c["accent"], text_color="#ffffff",
                             hover_color=c["accent"], border_color=c["accent"])
            except Exception: pass
        for w in self._reg_separators:
            try: w.configure(bg=c["border"])
            except Exception: pass
        for w in self._reg_scrollbars:
            try: w.configure(fg_color=c["bg"], button_color=c["btn"],
                             button_hover_color=c["accent"])
            except Exception: pass

        # Sidebar rows
        self._repaint_sidebar(c)

        # Status bar dots
        try:
            self._status_frame.configure(bg=c["bg"])
            for d in self._status_dots.values():
                d["frame"].configure(bg=c["bg"])
                d["lbl"].configure(bg=c["bg"], fg="#555")
                d["val"].configure(bg=c["bg"])
        except Exception:
            pass

        # Tab bar
        try:
            self._tab_bar.configure(bg=c["bg"])
            self._refresh_tab_styles(c)
        except Exception:
            pass

        # Progress bar trough
        try:
            self._progress_trough.configure(bg=c["btn"])
            self._progress_fill.configure(bg=c["accent"])
        except Exception:
            pass

        # Chips
        self._repaint_chips(c)

        # Preview and art
        self.preview_area.configure(bg=c["entry"], fg=c["fg"], insertbackground=c["fg"])
        self.log_area.configure(bg=c["entry"], fg=c["fg"])
        try:
            self._pv_visual_canvas.configure(bg=c["entry"])
            self.preview_inner.configure(bg=c["entry"])
        except Exception:
            pass

        self.art_label.configure(fg_color=c["entry"])
        if self._art_ctk_image is None:
            self._show_art_placeholder()

        self._paint_menu(c)
        self._save_config()

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _btn(self, parent, text, command, c, width=None, **kw):
        w = _ctk_btn(parent, text, command, c, width=width, **kw)
        self._reg_buttons.append(w)
        return w

    def _btn_accent(self, parent, text, command, c, width=None, **kw):
        kwargs = dict(text=text, command=command, fg_color=c["accent"],
                      text_color="#ffffff", hover_color=c["accent"],
                      border_width=0, corner_radius=4)
        if width: kwargs["width"] = width
        kwargs.update(kw)
        w = ctk.CTkButton(parent, **kwargs)
        self._reg_btn_accent.append(w)
        return w

    def _entry(self, parent, c, textvariable=None, width=None, justify="left", **kw):
        w = _ctk_entry(parent, c, textvariable=textvariable, width=width, justify=justify, **kw)
        self._reg_entries.append(w)
        return w

    def _label(self, parent, text, c, font=None, anchor="w", **kw):
        w = _ctk_label(parent, text, c, font=font, anchor=anchor, **kw)
        self._reg_labels.append((w, "fg"))
        return w

    def _combo(self, parent, c, values=None, command=None, width=160, **kw):
        w = _ctk_combo(parent, c, values=values, command=command, width=width, **kw)
        self._reg_combos.append(w)
        return w

    def _separator(self, parent, c):
        w = tk.Frame(parent, height=1, bg=c["border"])
        self._reg_separators.append(w)
        return w

    def _frame(self, parent, c, **kw):
        w = tk.Frame(parent, bg=c["bg"], **kw)
        self._reg_tk_frames.append(w)
        return w

    def _scrollbar(self, parent, orient, command, c):
        w = _ctk_scrollbar(parent, orient, command, c)
        self._reg_scrollbars.append(w)
        return w

    # ── Widget Construction ───────────────────────────────────────────────────

    def create_widgets(self, c):

        # ── Row 1: Toolbar ───────────────────────────────────────────────────
        toolbar = self._frame(self.root, c, pady=8)
        toolbar.pack(fill="x", padx=14)

        self._btn(toolbar, "Browse", self.browse_root, c, width=80).pack(side="left")

        path_e = self._entry(toolbar, c, textvariable=self.root_dir)
        path_e.pack(side="left", fill="x", expand=True, padx=(10, 10))

        # Breadcrumb: Artist › Album
        bc = self._frame(toolbar, c)
        bc.pack(side="left")
        self.artist_cb = self._combo(bc, c, width=190,
                                     command=lambda v: self.on_artist_select(None))
        self.artist_cb.pack(side="left")
        self._label(bc, " › ", c, font=ctk.CTkFont(size=13)).pack(side="left")
        self.album_cb = self._combo(bc, c, width=170,
                                    command=lambda v: self.on_album_select(None))
        self.album_cb.pack(side="left")

        self._btn(toolbar, "Batch", self.batch_preview_threaded, c,
                  width=60).pack(side="left", padx=(10, 0))

        # ── Row 2: Status bar ────────────────────────────────────────────────
        self._status_frame = tk.Frame(self.root, bg=c["bg"], pady=4)
        self._status_frame.pack(fill="x", padx=14)
        self._reg_tk_frames.append(self._status_frame)

        self._status_dots = {}
        self._build_status_dot("detect",  "Ready",       "#555",     c)
        self._build_status_dot("matched", "0 matched",   "#555",     c)
        self._build_status_dot("missing", "0 missing",   "#555",     c)
        self._build_status_dot("spotify", "Spotify",
                               "#2ecc71" if self.spot_engine.is_configured else "#555", c)

        sep_line = tk.Frame(self.root, height=1, bg=c["border"])
        self._reg_separators.append(sep_line)
        sep_line.pack(fill="x")

        # ── Body: Sidebar | Main | Art panel ─────────────────────────────────
        body = self._frame(self.root, c)
        body.pack(fill="both", expand=True)

        # Left sidebar — releases
        self._build_releases_sidebar(body, c)

        # Right art panel
        self._build_art_panel(body, c)

        # Centre — tabs + preview
        centre = self._frame(body, c)
        centre.pack(side="left", fill="both", expand=True)
        self._build_preview_tabs(centre, c)

        # ── Footer ────────────────────────────────────────────────────────────
        sep_foot = tk.Frame(self.root, height=1, bg=c["border"])
        self._reg_separators.append(sep_foot)
        sep_foot.pack(fill="x")

        footer = self._frame(self.root, c, pady=8)
        footer.pack(fill="x", padx=14)

        # Progress bar
        prog_wrap = self._frame(footer, c)
        prog_wrap.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._progress_trough = tk.Frame(prog_wrap, bg=c["btn"], height=4)
        self._progress_trough.pack(fill="x", pady=(6, 0))
        self._progress_fill = tk.Frame(self._progress_trough, bg=c["accent"], height=4, width=0)
        self._progress_fill.place(x=0, y=0, relheight=1.0, relwidth=0.0)

        self.progress_lbl = tk.Label(prog_wrap, text="No album loaded",
                                     bg=c["bg"], fg="#555", font=("Segoe UI", 9))
        self.progress_lbl.pack(anchor="w", pady=(2, 0))
        self._reg_tk_frames.append(prog_wrap)

        # Buttons
        self._btn(footer, "Undo", self.undo_rename, c, width=60).pack(side="right", padx=(6, 0))
        self._btn(footer, "Refresh", self.preview_renames, c, width=70).pack(side="right", padx=6)
        self._btn_accent(footer, "Execute Rename + Tag",
                         self._show_review_popup, c).pack(side="right")
        self._btn(footer, "Convert", self._show_convert_dialog, c,
                  width=70).pack(side="right", padx=(0, 8))

    # ── Status dot pills ──────────────────────────────────────────────────────

    def _build_status_dot(self, key, text, dot_color, c):
        f = tk.Frame(self._status_frame, bg=c["bg"])
        f.pack(side="left", padx=(0, 14))

        dot = tk.Frame(f, width=7, height=7, bg=dot_color)
        dot.pack(side="left", padx=(0, 4))
        dot.pack_propagate(False)

        lbl = tk.Label(f, text=text, bg=c["bg"], fg="#555",
                       font=("Segoe UI", 9))
        lbl.pack(side="left")

        self._status_dots[key] = {"frame": f, "dot": dot, "lbl": lbl, "val": lbl}

    def _set_status_dot(self, key, text, dot_color=None):
        try:
            d = self._status_dots[key]
            d["lbl"].configure(text=text)
            if dot_color:
                d["dot"].configure(bg=dot_color)
        except Exception:
            pass

    # ── Releases sidebar ──────────────────────────────────────────────────────

    def _build_releases_sidebar(self, parent, c):
        sidebar = tk.Frame(parent, bg=c["bg"], width=360)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._reg_tk_frames.append(sidebar)

        # Header
        hdr = tk.Frame(sidebar, bg=c["btn"])
        hdr.pack(fill="x")
        self._reg_tk_frames.append(hdr)
        tk.Label(hdr, text="SPOTIFY RELEASES", bg=c["btn"], fg="#aaa",
                 font=("Segoe UI", 10, "bold"), padx=10, pady=6).pack(side="left")
        self._sidebar_badge = tk.Label(hdr, text="0", bg="#0a1e30", fg="#0078d4",
                                       font=("Segoe UI", 8), padx=6)
        self._sidebar_badge.pack(side="right", padx=8)

        sep = tk.Frame(sidebar, height=1, bg=c["border"])
        sep.pack(fill="x")
        self._reg_separators.append(sep)

        # Scrollable canvas
        self._sidebar_canvas = tk.Canvas(sidebar, bg=c["entry"],
                                         highlightthickness=0)
        sb = ttk.Scrollbar(sidebar, orient="vertical",
                           command=self._sidebar_canvas.yview)
        self._sidebar_inner = tk.Frame(self._sidebar_canvas, bg=c["entry"])

        win_id = self._sidebar_canvas.create_window(
            (0, 0), window=self._sidebar_inner, anchor="nw")

        def on_inner_config(e):
            self._sidebar_canvas.configure(
                scrollregion=self._sidebar_canvas.bbox("all"))

        def on_canvas_config(e):
            self._sidebar_canvas.itemconfig(win_id, width=e.width)

        self._sidebar_inner.bind("<Configure>", on_inner_config)
        self._sidebar_canvas.bind("<Configure>", on_canvas_config)
        self._sidebar_canvas.bind("<MouseWheel>",
            lambda e: self._sidebar_canvas.yview_scroll(
                int(-1 * (e.delta / 120)), "units"))

        sb.pack(side="right", fill="y")
        self._sidebar_canvas.pack(side="left", fill="both", expand=True)

        sep2 = tk.Frame(sidebar, height=1, bg=c["border"])
        sep2.pack(fill="x", side="bottom")
        self._reg_separators.append(sep2)

    def _populate_release_sidebar(self, releases):
        c = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        for w in self._sidebar_inner.winfo_children():
            w.destroy()
        self._sidebar_rows = []

        for r in releases:
            self._add_sidebar_row(r, c)

        self._sidebar_badge.configure(text=str(len(releases)))

        # Load artwork for each row in background — staggered so we don't
        # hammer the network all at once
        def load_arts():
            import time
            for i, rd in enumerate(self._sidebar_rows):
                time.sleep(0.05 * i)   # 50 ms stagger per row
                try:
                    art_bytes = self.engine.get_cover_art_bytes(rd["id"])
                    if art_bytes:
                        self.root.after(0, self._paint_sidebar_art,
                                        rd["id"], art_bytes)
                except Exception:
                    pass

        threading.Thread(target=load_arts, daemon=True).start()

    def _add_sidebar_row(self, release, c):
        rid = release["id"]

        row = tk.Frame(self._sidebar_inner, bg=c["entry"], cursor="hand2")
        row.pack(fill="x")

        sep = tk.Frame(row, height=1, bg=c["bg"])
        sep.pack(fill="x")

        inner = tk.Frame(row, bg=c["entry"])
        inner.pack(fill="x", padx=10, pady=6)

        # Art placeholder square
        art = tk.Canvas(inner, width=72, height=72, bg="#1e1e1e",
                        highlightthickness=1, highlightbackground="#2a2a2a")
        art.pack(side="left", padx=(0, 10))
        art.create_text(36, 36, text="♪", fill="#333",
                        font=("Segoe UI", 22))

        # Info
        info = tk.Frame(inner, bg=c["entry"])
        info.pack(side="left", fill="x", expand=True)

        title_lbl = tk.Label(info, text=release["title"],
                             bg=c["entry"], fg=c["fg"],
                             font=("Segoe UI", 11), anchor="w",
                             cursor="hand2")
        title_lbl.pack(fill="x")

        rtype = release.get("type", "Album")
        badge_text = f"Single" if rtype.lower() == "single" else \
                     f"EP" if rtype.lower() == "ep" else ""
        meta_text = f"{release['year']}" + (f"  {badge_text}" if badge_text else "")
        meta_lbl = tk.Label(info, text=meta_text,
                            bg=c["entry"], fg="#777",
                            font=("Segoe UI", 9), anchor="w")
        meta_lbl.pack(fill="x")

        # Track count
        trk_lbl = tk.Label(inner, text=str(release.get("track_count", "?")),
                           bg=c["entry"], fg="#888",
                           font=("Segoe UI", 9))
        trk_lbl.pack(side="right")

        row_data = {
            "id": rid, "release": release,
            "row": row, "inner": inner, "art": art,
            "title_lbl": title_lbl, "meta_lbl": meta_lbl,
            "trk_lbl": trk_lbl, "sep": sep,
        }
        self._sidebar_rows.append(row_data)

        # Bind clicks on all children
        for w in [row, inner, art, info, title_lbl, meta_lbl, trk_lbl]:
            w.bind("<Button-1>",
                   lambda e, r=release: self._on_sidebar_click(r))

    def _paint_sidebar_art(self, release_id, art_bytes):
        """Paint a 72x72 thumbnail onto the sidebar row canvas for release_id."""
        if not PIL_AVAILABLE or not art_bytes:
            return
        try:
            import base64
            img = PilImage.open(io.BytesIO(art_bytes)).convert("RGB")
            img = img.resize((72, 72), _RESAMPLE)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
            for rd in self._sidebar_rows:
                if rd["id"] == release_id:
                    rd["art"].delete("all")
                    rd["art"].configure(width=72, height=72)
                    rd["art"].create_image(0, 0, anchor="nw", image=photo)
                    rd["_art_photo"] = photo
                    break
        except Exception:
            pass

    def _on_sidebar_click(self, release):
        self.current_release_id = release["id"]
        self._sidebar_highlight(release["id"])
        self._set_status(f"Loading {release['title']}…")
        self.current_tracks = self.engine.get_tracks(release["id"])
        threading.Thread(target=self._load_metadata_and_art,
                         args=(release["id"],), daemon=True).start()
        self.preview_renames()

    def _sidebar_highlight(self, release_id):
        c = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        for rd in self._sidebar_rows:
            selected = rd["id"] == release_id
            bg = "#0d2a45" if selected else c["entry"]
            fg = "#9fcde8" if selected else c["fg"]
            meta_fg = "#6aade8" if selected else "#555"
            trk_fg  = "#6aade8" if selected else "#444"
            for w in [rd["row"], rd["inner"], rd["title_lbl"],
                      rd["meta_lbl"], rd["trk_lbl"]]:
                try:
                    w.configure(bg=bg)
                except Exception:
                    pass
            rd["title_lbl"].configure(fg=fg)
            rd["meta_lbl"].configure(fg=meta_fg)
            rd["trk_lbl"].configure(fg=trk_fg)
            # Left accent border
            rd["row"].configure(highlightthickness=0)

    def _repaint_sidebar(self, c):
        try:
            self._sidebar_canvas.configure(bg=c["entry"])
            self._sidebar_inner.configure(bg=c["entry"])
            for rd in self._sidebar_rows:
                selected = rd["id"] == self.current_release_id
                bg = "#0d2a45" if selected else c["entry"]
                for w in [rd["row"], rd["inner"],
                          rd["title_lbl"], rd["meta_lbl"], rd["trk_lbl"]]:
                    try: w.configure(bg=bg)
                    except Exception: pass
                rd["sep"].configure(bg=c["bg"])
        except Exception:
            pass

    # ── Preview tabs ──────────────────────────────────────────────────────────

    def _build_preview_tabs(self, parent, c):

        # ── Tab bar ───────────────────────────────────────────────────────────
        self._tab_bar = tk.Frame(parent, bg=c["bg"])
        self._tab_bar.pack(fill="x")
        self._reg_tk_frames.append(self._tab_bar)

        self._tab_btns = {}
        for name in ["Preview", "Log"]:
            btn = tk.Button(self._tab_bar, text=name,
                            bg=c["bg"], fg="#555",
                            relief="flat", bd=0,
                            font=("Segoe UI", 9),
                            padx=14, pady=6, cursor="hand2",
                            command=lambda n=name: self._set_tab(n))
            btn.pack(side="left")
            self._tab_btns[name] = btn

        sep = tk.Frame(parent, height=1, bg=c["border"])
        sep.pack(fill="x")
        self._reg_separators.append(sep)

        # ── Content area ──────────────────────────────────────────────────────
        content = tk.Frame(parent, bg=c["entry"])
        content.pack(fill="both", expand=True)
        self._reg_tk_frames.append(content)

        # ── Visual preview frame (canvas-based scrollable rows) ───────────────
        self._pv_visual_outer = tk.Frame(content, bg=c["entry"])
        self._pv_visual_canvas = tk.Canvas(self._pv_visual_outer,
                                           bg=c["entry"], highlightthickness=0)
        self._pv_visual_sb = ttk.Scrollbar(self._pv_visual_outer, orient="vertical",
                                           command=self._pv_visual_canvas.yview)
        self.preview_inner = tk.Frame(self._pv_visual_canvas, bg=c["entry"])
        self._pv_win_id = self._pv_visual_canvas.create_window(
            (0, 0), window=self.preview_inner, anchor="nw")

        def _on_inner_cfg(e):
            self._pv_visual_canvas.configure(
                scrollregion=self._pv_visual_canvas.bbox("all"))

        def _on_canvas_cfg(e):
            self._pv_visual_canvas.itemconfig(self._pv_win_id, width=e.width)

        self.preview_inner.bind("<Configure>", _on_inner_cfg)
        self._pv_visual_canvas.bind("<Configure>", _on_canvas_cfg)
        self._pv_visual_canvas.bind("<MouseWheel>",
            lambda e: self._pv_visual_canvas.yview_scroll(
                int(-1 * (e.delta / 120)), "units"))

        self._pv_visual_sb.pack(side="right", fill="y")
        self._pv_visual_canvas.pack(side="left", fill="both", expand=True)

        # ── Hidden text widget kept for batch/write_preview fallback ──────────
        self.preview_area = tk.Text(content, font=("Courier", 10), wrap="none",
                                    bg=c["entry"], fg=c["fg"],
                                    insertbackground=c["fg"],
                                    relief="flat", bd=0, state="disabled")
        self._pv_vsb = ttk.Scrollbar(content, orient="vertical",
                                     command=self.preview_area.yview)
        self._pv_hsb = ttk.Scrollbar(content, orient="horizontal",
                                     command=self.preview_area.xview)
        self.preview_area.configure(yscrollcommand=self._pv_vsb.set,
                                    xscrollcommand=self._pv_hsb.set)

        # ── Tracklist and Log text widgets ────────────────────────────────────
        def make_text():
            t = tk.Text(content, font=("Courier", 10), wrap="none",
                        bg=c["entry"], fg=c["fg"],
                        insertbackground=c["fg"],
                        relief="flat", bd=0, state="disabled")
            vsb = ttk.Scrollbar(content, orient="vertical", command=t.yview)
            hsb = ttk.Scrollbar(content, orient="horizontal", command=t.xview)
            t.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            return t, vsb, hsb

        self.log_area, self._lg_vsb, self._lg_hsb = make_text()

        # Toast overlay
        self._toast = tk.Label(content, text="", bg="#0a180a", fg="#7ecf7e",
                               font=("Segoe UI", 9), padx=10, pady=5,
                               relief="flat", bd=0)

        # Configure tags for preview_area (used in batch/text fallback mode)
        self.preview_area.configure(state="normal")
        self.preview_area.tag_configure("hdr",  foreground=c["accent"],
                                        font=("Segoe UI", 9, "bold"))
        self.preview_area.tag_configure("arr",  foreground=c["accent"])
        self.preview_area.tag_configure("dim",  foreground=c["border"])
        self.preview_area.tag_configure("ok",   foreground="#2ecc71")
        self.preview_area.tag_configure("warn", foreground="#e67e22")
        self.preview_area.tag_configure("miss", foreground="#e74c3c")
        self.preview_area.configure(state="disabled")

        self._preview_text_mode = False  # False = visual rows, True = text widget
        self._set_tab("Preview")
        self._refresh_tab_styles(c)

    def _set_tab(self, name):
        self._active_tab = name
        c = THEMES.get(self.current_theme.get(), THEMES["Dark"])

        # Hide all
        for w in [self._pv_visual_outer,
                  self.preview_area, self._pv_vsb, self._pv_hsb,
                  self.log_area, self._lg_vsb, self._lg_hsb]:
            try:
                w.pack_forget()
            except Exception:
                pass

        if name == "Preview":
            if getattr(self, "_preview_text_mode", False):
                # Batch mode — show plain text widget
                self._pv_vsb.pack(side="right", fill="y")
                self._pv_hsb.pack(side="bottom", fill="x")
                self.preview_area.pack(side="left", fill="both", expand=True)
            else:
                # Single album mode — show visual rows
                self._pv_visual_outer.pack(fill="both", expand=True)
        else:
            self._lg_vsb.pack(side="right", fill="y")
            self._lg_hsb.pack(side="bottom", fill="x")
            self.log_area.pack(side="left", fill="both", expand=True)

        self._refresh_tab_styles(c)

    def _refresh_tab_styles(self, c):
        for name, btn in self._tab_btns.items():
            if name == self._active_tab:
                btn.configure(fg=c["accent"], bg=c["bg"])
            else:
                btn.configure(fg="#555", bg=c["bg"])

    # ── Art panel ─────────────────────────────────────────────────────────────

    def _build_art_panel(self, parent, c):
        panel = tk.Frame(parent, bg=c["bg"], width=210)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        self._reg_tk_frames.append(panel)

        sep = tk.Frame(panel, width=1, bg=c["border"])
        sep.pack(side="left", fill="y")
        self._reg_separators.append(sep)

        right = tk.Frame(panel, bg=c["bg"])
        right.pack(side="left", fill="both", expand=True)
        self._reg_tk_frames.append(right)

        # Art label
        wrap = tk.Frame(right, bg=c["bg"], pady=8)
        wrap.pack(fill="x", padx=8)
        self._reg_tk_frames.append(wrap)

        self.art_label = ctk.CTkLabel(wrap, text="", width=self.ART_SIZE,
                                      height=self.ART_SIZE, fg_color=c["entry"],
                                      corner_radius=4)
        self.art_label.pack()
        self._reg_labels.append((self.art_label, "fg"))
        self._show_art_placeholder()

        # Metadata rows
        self._meta_artist = tk.StringVar(value="—")
        self._meta_album  = tk.StringVar(value="—")
        self._meta_year   = tk.StringVar(value="—")
        self._meta_genre  = tk.StringVar(value="—")

        meta_frame = tk.Frame(right, bg=c["bg"])
        meta_frame.pack(fill="x", padx=8)
        self._reg_tk_frames.append(meta_frame)

        for lbl_text, var in [("Artist", self._meta_artist), ("Album", self._meta_album),
                               ("Year",  self._meta_year),   ("Genre", self._meta_genre)]:
            row = tk.Frame(meta_frame, bg=c["bg"])
            row.pack(fill="x", pady=1)
            self._reg_tk_frames.append(row)
            tk.Label(row, text=lbl_text, bg=c["bg"], fg="#555",
                     font=("Segoe UI", 8, "bold"), width=5, anchor="w").pack(side="left")
            lbl = tk.Label(row, textvariable=var, bg=c["bg"], fg=c["fg"],
                           font=("Segoe UI", 9), anchor="w", wraplength=148)
            lbl.pack(side="left", fill="x")
            self._reg_tk_frames.append(row)

        tk.Frame(right, height=1, bg=c["border"]).pack(fill="x", padx=8, pady=8)

        # Chip toggles
        chip_frame = tk.Frame(right, bg=c["bg"])
        chip_frame.pack(fill="x", padx=8)
        self._reg_tk_frames.append(chip_frame)

        tk.Label(chip_frame, text="APPLY TO FILES", bg=c["bg"], fg="#555",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 6))

        self._chip_btns = {}
        chips_row = tk.Frame(chip_frame, bg=c["bg"])
        chips_row.pack(fill="x")
        self._reg_tk_frames.append(chips_row)

        for key, text, var in [("art",   "Art",   self.apply_art),
                                ("tags",  "Tags",  self.apply_tags),
                                ("genre", "Genre", self.apply_genre)]:
            btn = tk.Button(chips_row, text=text, relief="flat",
                            font=("Segoe UI", 9), cursor="hand2",
                            padx=8, pady=3, bd=0)
            btn.pack(side="left", padx=(0, 4))
            self._chip_btns[key] = (btn, var)
            btn.configure(command=lambda v=var, b=btn: self._toggle_chip(v, b))

        self._repaint_chips(c)

        tk.Frame(right, height=1, bg=c["border"]).pack(fill="x", padx=8, pady=6)

        self._btn(right, "Fetch Artwork", self._fetch_art_threaded, c).pack(
            padx=8, fill="x")

    def _toggle_chip(self, var, btn):
        var.set(not var.get())
        c = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        self._style_chip(btn, var.get(), c)

    def _style_chip(self, btn, active, c):
        if active:
            btn.configure(bg=c["accent"], fg="#ffffff",
                          activebackground=c["accent"], activeforeground="#ffffff")
        else:
            btn.configure(bg=c["btn"], fg=c["fg"],
                          activebackground=c["btn"], activeforeground=c["fg"])

    def _repaint_chips(self, c):
        for key, (btn, var) in self._chip_btns.items():
            self._style_chip(btn, var.get(), c)

    # ── Progress bar ──────────────────────────────────────────────────────────

    def _update_progress(self, matched, total):
        try:
            ratio = matched / total if total > 0 else 0
            self._progress_fill.place(relwidth=ratio)
            self.progress_lbl.configure(
                text=f"{matched} / {total} tracks matched")
        except Exception:
            pass

    # ── Toast notification ────────────────────────────────────────────────────

    def _show_toast(self, text):
        try:
            self._toast.configure(text=f"  {text}  ")
            self._toast.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
            self.root.after(4000, self._hide_toast)
        except Exception:
            pass

    def _hide_toast(self):
        try:
            self._toast.place_forget()
        except Exception:
            pass

    # ── Art ───────────────────────────────────────────────────────────────────

    def _show_art_placeholder(self, text="No artwork"):
        try:
            self.art_label.configure(
                image=None, text=f"♪\n\n{text}",
                font=ctk.CTkFont(size=32),
                text_color=THEMES.get(self.current_theme.get(),
                                      THEMES["Dark"])["border"])
        except Exception:
            pass

    # ── Auto-detect ───────────────────────────────────────────────────────────

    def _auto_detect_artist(self, artist_name):
        if not self.spot_engine.is_configured:
            self._set_status_dot("detect", "Add Spotify creds in Settings", "#e74c3c")
            return
        self._set_status_dot("detect", f"Searching '{artist_name}'…", "#0078d4")

        artists = self.spot_engine.search_artists(artist_name)
        if not artists:
            self._set_status_dot("detect", f"No results for '{artist_name}'", "#e67e22")
            return

        from thefuzz import process, fuzz
        best = process.extractOne(artist_name, {a["id"]: a["name"] for a in artists},
                                  scorer=fuzz.token_set_ratio)
        artist_id    = best[2] if best else artists[0]["id"]
        matched_name = next(a["name"] for a in artists if a["id"] == artist_id)

        self.current_artist_id = artist_id
        self._set_status_dot("detect", f"✓ {matched_name}", "#2ecc71")

        releases = self.spot_engine.get_releases(artist_id)
        self._populate_release_sidebar(releases)
        self._known_releases = releases

    def _auto_detect_album(self, album_name):
        if not self.current_artist_id:
            return
        releases = getattr(self, "_known_releases", [])
        if not releases:
            return

        from thefuzz import process, fuzz
        release_map = {r["title"]: r for r in releases}
        match = process.extractOne(album_name, list(release_map.keys()),
                                   scorer=fuzz.token_set_ratio)
        if not match or match[1] < 40:
            self._set_status_dot("detect", f"No match for '{album_name}'", "#e67e22")
            return

        release = release_map[match[0]]
        self.current_release_id = release["id"]
        self._sidebar_highlight(release["id"])

        self.current_tracks = self.spot_engine.get_tracks(release["id"])
        self._set_status_dot("detect",
            f"✓ {release['title']} ({release['year']})", "#2ecc71")

        threading.Thread(target=self._load_metadata_and_art,
                         args=(release["id"],), daemon=True).start()
        self.preview_renames()

    def _set_detect_status(self, text):
        self._set_status_dot("detect", text)

    # ── Settings dialog ───────────────────────────────────────────────────────

    def _open_settings(self):
        c   = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("480x580")
        win.resizable(False, False)
        win.configure(bg=c["bg"])
        win.update_idletasks()
        win.grab_set()
        win.lift()
        win.focus_force()

        def row(parent, label_text, show=""):
            f = tk.Frame(parent, bg=c["bg"])
            f.pack(fill="x", pady=(0, 10))
            tk.Label(f, text=label_text, bg=c["bg"], fg=c["fg"],
                     font=("Segoe UI", 11)).pack(anchor="w")
            e = _ctk_entry(f, c, show=show)
            e.pack(fill="x", pady=(4, 0))
            return e

        pad = tk.Frame(win, bg=c["bg"], padx=28, pady=24)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Spotify API Credentials", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(pad, text="Get a free Client ID + Secret at developer.spotify.com/dashboard",
                 bg=c["bg"], fg=c["fg"], font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

        id_entry     = row(pad, "Client ID")
        secret_entry = row(pad, "Client Secret", show="•")
        id_entry.insert(0, self._spotify_id)
        secret_entry.insert(0, self._spotify_secret)

        tk.Frame(pad, height=1, bg=c["border"]).pack(fill="x", pady=14)

        tk.Label(pad, text="Default media path", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 11)).pack(anchor="w")
        path_row = tk.Frame(pad, bg=c["bg"])
        path_row.pack(fill="x", pady=(4, 0))
        path_e = _ctk_entry(path_row, c, textvariable=self.root_dir)
        path_e.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Button(path_row, text="Browse",
                  command=lambda: self.root_dir.set(d) if (d := filedialog.askdirectory()) else None,
                  bg=c["btn"], fg=c["fg"], relief="flat",
                  activebackground=c["accent"], activeforeground="#ffffff",
                  padx=10, pady=4, cursor="hand2").pack(side="right")

        tk.Frame(pad, height=1, bg=c["border"]).pack(fill="x", pady=14)

        # ── Pre-execution automation ──────────────────────────────────────────
        tk.Label(pad, text="Pre-execution Automation", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

        remux_var = tk.BooleanVar(value=self._auto_remux)
        remux_chk = tk.Checkbutton(pad,
                                   text="Auto-remux non-MP3/FLAC files before rename",
                                   variable=remux_var, bg=c["bg"], fg=c["fg"],
                                   selectcolor=c["entry"], activebackground=c["bg"],
                                   activeforeground=c["fg"], font=("Segoe UI", 10))
        remux_chk.pack(anchor="w")

        remux_opts = tk.Frame(pad, bg=c["bg"])
        remux_opts.pack(fill="x", pady=(8, 0), padx=(20, 0))

        tk.Label(remux_opts, text="Target format:", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 10)).pack(side="left")
        remux_fmt_var = tk.StringVar(value=self._auto_remux_target)
        remux_fmt_cb = _ctk_combo(remux_opts, c,
                                  values=sorted(SUPPORTED_OUTPUT), width=100)
        remux_fmt_cb.configure(variable=remux_fmt_var)
        remux_fmt_cb.pack(side="left", padx=(8, 20))

        tk.Label(remux_opts, text="Quality:", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 10)).pack(side="left")
        remux_qual_var = tk.StringVar(value=self._auto_remux_quality)
        remux_qual_cb = _ctk_combo(remux_opts, c,
                                   values=["low", "medium", "high", "best"], width=100)
        remux_qual_cb.configure(variable=remux_qual_var)
        remux_qual_cb.pack(side="left", padx=(8, 0))

        remux_del_var = tk.BooleanVar(value=self._auto_remux_del_src)
        tk.Checkbutton(pad, text="Delete source file after conversion",
                       variable=remux_del_var, bg=c["bg"], fg=c["fg"],
                       selectcolor=c["entry"], activebackground=c["bg"],
                       activeforeground=c["fg"], font=("Segoe UI", 9)
                       ).pack(anchor="w", padx=(20, 0), pady=(6, 0))

        def _toggle_remux_opts():
            state = "normal" if remux_var.get() else "disabled"
            for w in remux_opts.winfo_children():
                try: w.configure(state=state)
                except Exception: pass
            remux_del_var.set(remux_del_var.get() if remux_var.get() else False)

        remux_chk.configure(command=_toggle_remux_opts)
        _toggle_remux_opts()

        def save():
            cid  = id_entry.get().strip()
            csec = secret_entry.get().strip()
            if cid and csec:
                self.spot_engine.configure(cid, csec)
                if not self.spot_engine.is_configured:
                    messagebox.showerror("Invalid credentials",
                        "Spotify rejected the credentials.", parent=win)
                    return
                self._set_status_dot("spotify", "Spotify connected", "#2ecc71")
            self._spotify_id        = cid
            self._spotify_secret    = csec
            self._auto_remux        = remux_var.get()
            self._auto_remux_target = remux_fmt_var.get()
            self._auto_remux_quality  = remux_qual_var.get()
            self._auto_remux_del_src  = remux_del_var.get()
            self._save_config()
            messagebox.showinfo("Saved", "Settings saved.", parent=win)
            win.destroy()

        tk.Button(pad, text="Save", command=save,
                  bg=c["accent"], fg="#ffffff", relief="flat",
                  activebackground=c["accent"], activeforeground="#ffffff",
                  padx=16, pady=6, cursor="hand2",
                  font=("Segoe UI", 10, "bold")).pack(anchor="e", pady=(16, 0))

    # ── Release selection (manual override via sidebar) ───────────────────────

    def on_release_select(self, release_id):
        self.current_release_id = release_id
        self._set_status(f"Loading tracks…")
        self.current_tracks = self.engine.get_tracks(release_id)
        threading.Thread(target=self._load_metadata_and_art,
                         args=(release_id,), daemon=True).start()
        self.preview_renames()

    # ── Metadata & Artwork ────────────────────────────────────────────────────

    def _load_metadata_and_art(self, release_id):
        self.root.after(0, self._show_art_placeholder, "Loading…")
        meta      = self.engine.get_release_metadata(release_id)
        art_bytes = self.engine.get_cover_art_bytes(release_id)
        self.root.after(0, self._update_metadata_panel, meta)
        self.root.after(0, self._update_art_panel, art_bytes)

    def _fetch_art_threaded(self):
        if not self.current_release_id:
            messagebox.showwarning("No Release", "Select a release first.")
            return
        self._set_status("Fetching artwork…")
        self._show_art_placeholder("Loading…")
        threading.Thread(
            target=lambda: self.root.after(0, self._update_art_panel,
                self.engine.get_cover_art_bytes(self.current_release_id)),
            daemon=True).start()

    def _update_metadata_panel(self, meta):
        self.current_metadata = meta
        self._meta_artist.set(meta.get("artist", "—") or "—")
        self._meta_album.set( meta.get("album",  "—") or "—")
        self._meta_year.set(  meta.get("year",   "—") or "—")
        self._meta_genre.set( meta.get("genre",  "—") or "—")
        if meta.get("genre"):
            self._set_status_dot("detect",
                f"✓ {meta.get('album','')}  ·  {meta['genre']}", "#2ecc71")

    def _update_art_panel(self, art_bytes):
        self.current_art_bytes = art_bytes
        if not art_bytes:
            self._show_art_placeholder(); return

        if not PIL_AVAILABLE:
            detail = f"\n\n({PIL_ERROR[:60]})" if PIL_ERROR else ""
            self._show_art_placeholder(f"pip install Pillow{detail}"); return

        try:
            img = PilImage.open(io.BytesIO(art_bytes)).convert("RGB")
            img = img.resize((self.ART_SIZE, self.ART_SIZE), _RESAMPLE)
        except Exception as e:
            self._show_art_placeholder(f"Decode error:\n{e}"); return

        try:
            import base64
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue())

            if not hasattr(self, "_art_canvas_fallback"):
                parent = self.art_label.master
                self.art_label.pack_forget()
                self._art_canvas_fallback = tk.Canvas(
                    parent, width=self.ART_SIZE, height=self.ART_SIZE,
                    highlightthickness=0,
                    bg=THEMES.get(self.current_theme.get(), THEMES["Dark"])["entry"])
                self._art_canvas_fallback.pack()

            self._art_photo = tk.PhotoImage(data=b64)
            self._art_canvas_fallback.delete("all")
            self._art_canvas_fallback.create_image(0, 0, anchor="nw",
                                                   image=self._art_photo)
        except Exception as e:
            self._show_art_placeholder(f"{type(e).__name__}:\n{str(e)[:80]}")

    # ── Preview ───────────────────────────────────────────────────────────────

    def preview_renames(self):
        if not self.current_tracks:
            return
        p = self.selected_album_path.get()
        if not p or not os.path.exists(p):
            return

        self.episodes_data, log = self.engine.generate_fuzzy_preview(
            p, self.current_tracks)

        file_count   = len([f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))])
        matched_keys = {(dnum, tnum) for _, _, tnum, dnum, *_ in self.episodes_data}
        missing      = [t for t in self.current_tracks
                        if (t.get("disc", 1), t["num"]) not in matched_keys]

        # ── Update progress bar ───────────────────────────────────────────────
        self._update_progress(len(self.episodes_data), len(self.current_tracks))

        # ── Status dot pills ──────────────────────────────────────────────────
        self._set_status_dot("matched",
            f"{len(self.episodes_data)} / {len(self.current_tracks)} matched",
            "#2ecc71" if len(self.episodes_data) == len(self.current_tracks) else "#0078d4")
        self._set_status_dot("missing",
            f"{len(missing)} missing",
            "#e74c3c" if missing else "#555")

        # ── Toast for unmatched files ─────────────────────────────────────────
        unmatched_files = [f for f in os.listdir(p)
                           if os.path.isfile(os.path.join(p, f))
                           and f not in {old for old, *_ in self.episodes_data}]
        if unmatched_files:
            self._show_toast(f"{len(unmatched_files)} files need manual pairing")

        # ── Build visual track rows in preview tab ────────────────────────────
        self._preview_text_mode = False
        if self._active_tab == "Preview":
            self._set_tab("Preview")
        self._build_track_rows(self.episodes_data, missing, p)

        # ── Populate log tab ──────────────────────────────────────────────────
        self.log_area.configure(state="normal")
        self.log_area.delete("1.0", tk.END)
        self.log_area.insert(tk.END, log)
        self.log_area.configure(state="disabled")

        self.batch_data = []

    # ── Visual preview rows ───────────────────────────────────────────────────

    def _build_track_rows(self, ep_data, missing_tracks, folder):
        """Populate the preview canvas with visual per-track rows."""
        c = THEMES.get(self.current_theme.get(), THEMES["Dark"])

        for w in self.preview_inner.winfo_children():
            w.destroy()

        total    = len(self.current_tracks)
        matched  = len(ep_data)
        miss_n   = len(missing_tracks)

        # Header summary bar
        hdr = tk.Frame(self.preview_inner, bg=c["bg"], padx=10, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr,
                 text=f"{matched} matched  ·  {miss_n} unmatched  ·  {total} total",
                 bg=c["bg"], fg="#888", font=("Segoe UI", 9)).pack(side="left")
        tk.Frame(self.preview_inner, height=1, bg=c["border"]).pack(fill="x",
                                                                     padx=8, pady=(0, 4))

        # Build lookup: (disc, num) → (old_file, new_name, score)
        ep_lookup = {}
        for item in ep_data:
            old, new, tnum, dnum = item[0], item[1], item[2], item[3]
            score = item[4] if len(item) > 4 else 100
            ep_lookup[(dnum, tnum)] = (old, new, score)

        for track in self.current_tracks:
            key = (track.get("disc", 1), track["num"])
            if key in ep_lookup:
                old, new, score = ep_lookup[key]
                self._add_preview_row(track, old, new, score, c)
            else:
                self._add_preview_row(track, None, None, 0, c)

        # Update scroll region
        self.preview_inner.update_idletasks()
        self._pv_visual_canvas.configure(
            scrollregion=self._pv_visual_canvas.bbox("all"))

    def _add_preview_row(self, track, old_file, new_file, score, c):
        """Render a single track row in the visual preview."""
        unmatched = old_file is None
        warning   = (not unmatched) and score < 80

        if unmatched:
            row_bg  = "#2a0d0d"
            bdr_clr = "#6b1f1f"
        elif warning:
            row_bg  = "#291d09"
            bdr_clr = "#6b4a0d"
        else:
            row_bg  = c["btn"]
            bdr_clr = c["border"]

        outer = tk.Frame(self.preview_inner, bg=bdr_clr, padx=1, pady=1)
        outer.pack(fill="x", padx=8, pady=2)
        row = tk.Frame(outer, bg=row_bg, padx=8, pady=7)
        row.pack(fill="x")

        # Track number
        tk.Label(row, text=f"{track['num']:>2}", bg=row_bg, fg="#555",
                 font=("Segoe UI", 9), width=2, anchor="e").pack(side="left",
                                                                  padx=(0, 8))

        # Centre info
        info = tk.Frame(row, bg=row_bg)
        info.pack(side="left", fill="x", expand=True)

        name_text = track["name"]
        if track.get("disc", 1) > 1:
            name_text += f"  [Disc {track['disc']}]"
        name_fg = c["fg"] if not unmatched else "#884444"

        tk.Label(info, text=name_text, bg=row_bg, fg=name_fg,
                 font=("Segoe UI", 10), anchor="w").pack(fill="x")

        file_text = old_file if old_file else "— no file found"
        tk.Label(info, text=file_text, bg=row_bg, fg="#555",
                 font=("Segoe UI", 8), anchor="w").pack(fill="x")

        if unmatched:
            # Unmatched badge
            badge = tk.Label(row, text="unmatched", bg="#6b1f1f", fg="#ffaaaa",
                             font=("Segoe UI", 8), padx=6, pady=2)
            badge.pack(side="right", padx=(6, 0))
            assign_btn = tk.Button(
                row, text="assign", bg=c["btn"], fg="#888",
                font=("Segoe UI", 8), relief="flat", bd=1,
                highlightbackground=c["border"], padx=8, pady=2,
                cursor="hand2",
                command=lambda t=track: self._do_assign(t))
            assign_btn.pack(side="right", padx=(4, 0))
        else:
            # Arrow
            tk.Label(row, text="→", bg=row_bg, fg="#555",
                     font=("Segoe UI", 9)).pack(side="left", padx=6)

            # Confidence bar + percentage
            conf_wrap = tk.Frame(row, bg=row_bg, width=90)
            conf_wrap.pack(side="left", padx=4)
            conf_wrap.pack_propagate(False)

            bar_trough = tk.Frame(conf_wrap, bg=c["border"], height=4)
            bar_trough.pack(fill="x", pady=(4, 0))
            bar_color = "#2ecc71" if score >= 80 else "#e67e22" if score >= 55 else "#e74c3c"
            bar_fill  = tk.Frame(bar_trough, bg=bar_color, height=4)
            bar_fill.place(x=0, y=0, relheight=1.0, relwidth=min(score / 100, 1.0))
            tk.Label(conf_wrap, text=f"{score}%", bg=row_bg, fg="#666",
                     font=("Segoe UI", 8), anchor="e").pack(fill="x")

            # Swap button
            swap_btn = tk.Button(
                row, text="swap", bg=c["btn"], fg=c["fg"],
                font=("Segoe UI", 8), relief="flat", bd=1,
                highlightbackground=c["border"], padx=8, pady=2,
                cursor="hand2",
                command=lambda t=track, of=old_file: self._do_swap(t, of))
            swap_btn.pack(side="right", padx=(4, 0))

        # Bind scroll on row widgets too
        for w in [outer, row, info]:
            w.bind("<MouseWheel>",
                   lambda e: self._pv_visual_canvas.yview_scroll(
                       int(-1 * (e.delta / 120)), "units"))

    def _do_swap(self, track, current_file):
        """Let the user pick a different file to assign to this track."""
        folder = self.selected_album_path.get()
        if not folder or not os.path.exists(folder):
            return

        matched_files = {old for old, *_ in self.episodes_data}
        available     = sorted([f for f in os.listdir(folder)
                                 if os.path.isfile(os.path.join(folder, f))
                                 and f != current_file])

        c   = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        win = tk.Toplevel(self.root)
        win.title(f"Swap: {track['name']}")
        win.geometry("420x300")
        win.resizable(False, True)
        win.configure(bg=c["bg"])
        win.grab_set()
        win.lift()
        win.focus_force()

        tk.Label(win, text=f'Reassign "{track["name"]}" to:',
                 bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 10), padx=14, pady=10).pack(anchor="w")

        frame = tk.Frame(win, bg=c["entry"])
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        sb = ttk.Scrollbar(frame, orient="vertical")
        lb = tk.Listbox(frame, bg=c["entry"], fg=c["fg"],
                        selectbackground=c["accent"], selectforeground="#ffffff",
                        relief="flat", bd=0, highlightthickness=0,
                        activestyle="none", font=("Segoe UI", 10),
                        yscrollcommand=sb.set)
        sb.config(command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)

        for f in available:
            already = "✓ " if f in matched_files else "  "
            lb.insert(tk.END, f"  {already}{f}")

        def confirm():
            sel = lb.curselection()
            if not sel:
                return
            new_file = available[sel[0]]
            ext      = os.path.splitext(new_file)[1]
            from base_engine import BaseEngine as _BE
            be = _BE.__new__(_BE)
            new_name = be._track_filename(track, ext)
            # Remove old entry for this track and for the chosen file
            self.episodes_data = [
                e for e in self.episodes_data
                if not (e[2] == track["num"] and e[3] == track.get("disc", 1))
                and e[0] != new_file
            ]
            self.episodes_data.append(
                (new_file, new_name, track["num"], track.get("disc", 1), 100))
            win.destroy()
            self.preview_renames()

        foot = tk.Frame(win, bg=c["bg"], pady=8)
        foot.pack(fill="x", padx=14)
        tk.Button(foot, text="Cancel", command=win.destroy,
                  bg=c["btn"], fg=c["fg"], relief="flat",
                  padx=12, pady=4, cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(foot, text="Confirm", command=confirm,
                  bg=c["accent"], fg="#ffffff", relief="flat",
                  padx=12, pady=4, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="right")

    def _do_assign(self, track):
        """Let the user assign an unmatched file to this track."""
        folder = self.selected_album_path.get()
        if not folder or not os.path.exists(folder):
            return

        matched_files = {old for old, *_ in self.episodes_data}
        available     = sorted([f for f in os.listdir(folder)
                                 if os.path.isfile(os.path.join(folder, f))
                                 and f not in matched_files])

        c   = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        win = tk.Toplevel(self.root)
        win.title(f"Assign: {track['name']}")
        win.geometry("420x300")
        win.resizable(False, True)
        win.configure(bg=c["bg"])
        win.grab_set()
        win.lift()
        win.focus_force()

        tk.Label(win, text=f'Assign a file to "{track["name"]}":',
                 bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 10), padx=14, pady=10).pack(anchor="w")

        frame = tk.Frame(win, bg=c["entry"])
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        sb = ttk.Scrollbar(frame, orient="vertical")
        lb = tk.Listbox(frame, bg=c["entry"], fg=c["fg"],
                        selectbackground=c["accent"], selectforeground="#ffffff",
                        relief="flat", bd=0, highlightthickness=0,
                        activestyle="none", font=("Segoe UI", 10),
                        yscrollcommand=sb.set)
        sb.config(command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)

        for f in available:
            lb.insert(tk.END, f"  {f}")

        if not available:
            lb.insert(tk.END, "  (no unmatched files remaining)")

        def confirm():
            sel = lb.curselection()
            if not sel or not available:
                return
            chosen_file = available[sel[0]]
            ext         = os.path.splitext(chosen_file)[1]
            from base_engine import BaseEngine as _BE
            be = _BE.__new__(_BE)
            new_name = be._track_filename(track, ext)
            self.episodes_data.append(
                (chosen_file, new_name, track["num"], track.get("disc", 1), 100))
            win.destroy()
            self.preview_renames()

        foot = tk.Frame(win, bg=c["bg"], pady=8)
        foot.pack(fill="x", padx=14)
        tk.Button(foot, text="Cancel", command=win.destroy,
                  bg=c["btn"], fg=c["fg"], relief="flat",
                  padx=12, pady=4, cursor="hand2").pack(side="right", padx=(6, 0))
        tk.Button(foot, text="Assign", command=confirm,
                  bg=c["accent"], fg="#ffffff", relief="flat",
                  padx=12, pady=4, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="right")

    # ── Batch ─────────────────────────────────────────────────────────────────

    def batch_preview_threaded(self):
        if not self.current_artist_id:
            messagebox.showwarning("No Artist", "Select an artist folder first.")
            return
        p = self.selected_artist_path.get()
        if not p or not os.path.exists(p):
            messagebox.showwarning("No Folder", "Select an artist folder first.")
            return
        self._set_status_dot("detect", "Running batch preview…", "#e67e22")
        self._write_preview("Running batch preview — please wait…\n")
        threading.Thread(target=self._batch_worker, args=(p,), daemon=True).start()

    def _batch_worker(self, path):
        results = self.engine.generate_batch_preview(
            path, self.current_artist_id, "Fuzzy")
        self.root.after(0, self._batch_done, results)

    def _batch_done(self, results):
        self.batch_data    = results
        self.episodes_data = []
        self._preview_text_mode = True
        total_files   = sum(
            len([f for f in os.listdir(r["path"]) if os.path.isfile(os.path.join(r["path"], f))])
            for r in results if os.path.exists(r["path"])
        )
        total_matches = sum(len(r["ep_data"]) for r in results)
        header = (
            f"BATCH PREVIEW  ─  {self.artist_cb.get()}\n"
            f"{'═' * 55}\n"
            f"Albums: {len(results)}  ·  Files: {total_files}  ·  Matches: {total_matches}\n"
            f"{'═' * 55}\n\n"
        )
        self._write_preview(header + "\n".join(r["log"] for r in results))
        self._update_progress(total_matches, total_files)
        self._set_status_dot("matched", f"{total_matches} / {total_files} matched",
                             "#2ecc71" if total_matches == total_files else "#0078d4")
        self._set_status_dot("detect",
            f"Batch: {len(results)} albums", "#2ecc71")

    def _show_review_popup(self):
        """Two-panel dialog: unmatched files (left) + available Spotify tracks
        (right). Click a file then a track to pair them manually before executing."""

        if not self.episodes_data and not self.batch_data:
            messagebox.showinfo("Nothing to do", "Run a preview first.")
            return

        # ── Collect unmatched files and available tracks ──────────────────────
        folder      = self.selected_album_path.get()
        matched_old = {old for old, *_ in self.episodes_data}

        if os.path.exists(folder):
            unmatched_files = [
                f for f in sorted(os.listdir(folder))
                if os.path.isfile(os.path.join(folder, f))
                and f not in matched_old
            ]
        else:
            unmatched_files = []

        # Right panel shows the FULL Spotify tracklist so the user can
        # always see and pick any track, not just ones without auto-matches.
        available_tracks = list(self.current_tracks)

        # Already-paired track keys (disc, num) — prevents double-pairing
        already_matched = {(dnum, tnum) for _, _, tnum, dnum, *_ in self.episodes_data}

        # If nothing to pair, skip straight to execute
        if not unmatched_files:
            self.execute_rename()
            return

        # ── State ─────────────────────────────────────────────────────────────
        manual_pairs      = []
        paired_files      = set()
        paired_track_keys = set(already_matched)  # pre-seed with auto-matched so they can't be double-paired
        _sel_file_idx     = [None]

        c   = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        win = tk.Toplevel(self.root)
        win.title("Unmatched Files")
        win.geometry("680x480")
        win.resizable(True, True)
        win.configure(bg=c["bg"])
        win.update_idletasks()
        win.grab_set()
        win.lift()
        win.focus_force()

        # ── Hint row ──────────────────────────────────────────────────────────
        hint = tk.Label(
            win,
            text="Click a file  →  click a Spotify track  →  they'll be paired below.",
            bg=c["bg"], fg="#555",
            font=("Segoe UI", 9), anchor="w", padx=14, pady=8
        )
        hint.pack(fill="x")
        tk.Frame(win, height=1, bg=c["border"]).pack(fill="x")

        # ── Two-panel body ────────────────────────────────────────────────────
        body = tk.Frame(win, bg=c["bg"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        def panel_header(parent, text, badge_text, badge_fg, badge_bg):
            f = tk.Frame(parent, bg=c["btn"])
            tk.Label(f, text=text, bg=c["btn"], fg="#888",
                     font=("Segoe UI", 9, "bold"),
                     anchor="w", padx=10, pady=6).pack(side="left")
            tk.Label(f, text=badge_text, bg=badge_bg, fg=badge_fg,
                     font=("Segoe UI", 8), padx=6, pady=2).pack(side="right", padx=8)
            return f

        def make_listbox(parent, bg_sel):
            frame = tk.Frame(parent, bg=c["entry"])
            sb    = ttk.Scrollbar(frame, orient="vertical")
            lb    = tk.Listbox(frame, bg=c["entry"], fg=c["fg"],
                               selectbackground=bg_sel, selectforeground="#ffffff",
                               relief="flat", bd=0, highlightthickness=0,
                               activestyle="none", font=("Segoe UI", 10),
                               exportselection=False,   # ← keeps selection when focus moves
                               yscrollcommand=sb.set)
            sb.config(command=lb.yview)
            sb.pack(side="right", fill="y")
            lb.pack(side="left", fill="both", expand=True)
            return frame, lb

        # Left panel — unmatched files
        left = tk.Frame(body, bg=c["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        file_hdr_lbl = panel_header(left, "YOUR FILES",
                                    f"{len(unmatched_files)} unmatched",
                                    "#e67e22", "#2e1a08")
        file_hdr_lbl.pack(fill="x")
        lf, file_lb = make_listbox(left, "#c45f00")
        lf.pack(fill="both", expand=True)

        for f in unmatched_files:
            file_lb.insert(tk.END, f"  {f}")

        # Right panel — available Spotify tracks
        right = tk.Frame(body, bg=c["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        track_hdr_lbl = panel_header(right, "SPOTIFY TRACKS",
                                     f"{len(available_tracks)} tracks",
                                     "#0078d4", "#0a1e30")
        track_hdr_lbl.pack(fill="x")
        rf, track_lb = make_listbox(right, "#004a80")
        rf.pack(fill="both", expand=True)

        def track_label(t):
            disc   = f"  [Disc {t['disc']}]" if t.get("disc", 1) > 1 else ""
            tkey   = (t.get("disc", 1), t["num"])
            prefix = "  ✓ " if tkey in already_matched else "     "
            return f"{prefix}{t['num']:>2}.  {t['name']}{disc}"

        for t in available_tracks:
            track_lb.insert(tk.END, track_label(t))
            # Dim already-matched tracks so they're visually distinct
            tkey = (t.get("disc", 1), t["num"])
            if tkey in already_matched:
                track_lb.itemconfig(tk.END, fg="#444")

        # ── Paired section ────────────────────────────────────────────────────
        tk.Frame(win, height=1, bg=c["border"]).pack(fill="x")

        paired_hdr = tk.Label(win, text="MANUALLY PAIRED (0)",
                              bg="#090f09", fg="#2ecc71",
                              font=("Segoe UI", 9, "bold"),
                              anchor="w", padx=10, pady=5)
        paired_hdr.pack(fill="x")

        paired_frame = tk.Frame(win, bg=c["bg"], height=60)
        paired_frame.pack(fill="x")
        paired_frame.pack_propagate(False)

        paired_list = tk.Text(paired_frame, bg=c["entry"], fg="#7ecf7e",
                              font=("Courier", 9), relief="flat", bd=0,
                              state="disabled", height=3)
        paired_list.pack(fill="both", expand=True)

        def refresh_paired():
            paired_hdr.config(text=f"MANUALLY PAIRED ({len(manual_pairs)})")
            paired_list.config(state="normal")
            paired_list.delete("1.0", tk.END)
            for fname, track in manual_pairs:
                paired_list.insert(tk.END, f"  {fname}  →  {track['name']}\n")
            paired_list.config(state="disabled")
            remaining = len(unmatched_files) - len(manual_pairs)
            footer_lbl.config(
                text="All files paired" if remaining == 0
                else f"{remaining} still unpaired — will be skipped"
            )

        # ── Pairing logic ─────────────────────────────────────────────────────

        def do_pair():
            fi = _sel_file_idx[0]
            ti = track_lb.curselection()
            if fi is None or not ti:
                return
            ti = ti[0]
            if fi >= file_lb.size():
                return

            fname = file_lb.get(fi).strip()
            track = available_tracks[ti]
            tkey  = (track.get("disc", 1), track["num"])

            if fname in paired_files or tkey in paired_track_keys:
                hint.config(
                    text="That track is already matched — pick a different one.")
                return

            manual_pairs.append((fname, track))
            paired_files.add(fname)
            paired_track_keys.add(tkey)

            # Remove file from left list (it's now handled)
            file_lb.delete(fi)
            _sel_file_idx[0] = None

            # Mark track as paired in right list (dim + tick) — don't remove it
            track_lb.itemconfig(ti, fg="#2ecc71")
            track_lb.itemconfig(ti, selectforeground="#2ecc71")

            # Update badge
            file_hdr_lbl.winfo_children()[1].config(
                text=f"{file_lb.size()} unmatched")

            hint.config(
                text="Click a file  →  click a Spotify track  →  they'll be paired below.")
            refresh_paired()

        def on_file_click(evt):
            sel = file_lb.curselection()
            if sel:
                _sel_file_idx[0] = sel[0]
                # Highlight hint
                hint.config(text="File selected — now click a Spotify track to pair.")

        def on_track_click(evt):
            # If a file is already selected, pair immediately
            if _sel_file_idx[0] is not None:
                win.after(10, do_pair)
            # If no file selected, nudge the user
            elif not file_lb.curselection():
                hint.config(
                    text="Click a file on the left first, then a Spotify track.")

        file_lb.bind("<<ListboxSelect>>", on_file_click)
        file_lb.bind("<Double-1>",        lambda e: on_file_click(e))
        track_lb.bind("<<ListboxSelect>>", on_track_click)
        track_lb.bind("<Double-1>",        lambda e: on_track_click(e))

        # ── Footer ────────────────────────────────────────────────────────────
        tk.Frame(win, height=1, bg=c["border"]).pack(fill="x")
        foot = tk.Frame(win, bg=c["bg"], pady=10)
        foot.pack(fill="x", padx=14)

        footer_lbl = tk.Label(foot, text=f"{len(unmatched_files)} unmatched — will be skipped",
                              bg=c["bg"], fg="#555", font=("Segoe UI", 9))
        footer_lbl.pack(side="left")

        def confirm():
            # Inject manual pairs into episodes_data then execute
            from base_engine import BaseEngine
            engine_inst = BaseEngine.__new__(BaseEngine)
            for fname, track in manual_pairs:
                ext      = os.path.splitext(fname)[1]
                new_name = engine_inst._track_filename(track, ext)
                self.episodes_data.append(
                    (fname, new_name, track["num"], track.get("disc", 1), 100)
                )
            win.destroy()
            self.execute_rename()

        tk.Button(foot, text="Cancel", command=win.destroy,
                  bg=c["btn"], fg=c["fg"], relief="flat",
                  activebackground=c["border"], activeforeground=c["fg"],
                  padx=14, pady=5, cursor="hand2").pack(side="right", padx=(8, 0))

        tk.Button(foot, text="Confirm & Execute", command=confirm,
                  bg=c["accent"], fg="#ffffff", relief="flat",
                  activebackground=c["accent"], activeforeground="#ffffff",
                  padx=14, pady=5, cursor="hand2",
                  font=("Segoe UI", 9, "bold")).pack(side="right")

    # ── Execute ───────────────────────────────────────────────────────────────

    def execute_rename(self):
        history, renamed, tagged = [], 0, 0
        pairs = []
        if self.batch_data:
            pairs = [(r["path"], old, new, tnum, dnum)
                     for r in self.batch_data
                     for old, new, tnum, dnum, *_ in r["ep_data"]]
        elif self.episodes_data:
            p = self.selected_album_path.get()
            pairs = [(p, old, new, tnum, dnum)
                     for old, new, tnum, dnum, *_ in self.episodes_data]

        if not pairs:
            messagebox.showinfo("Nothing to do", "Run a preview first.")
            return

        # ── Pre-execution remux ───────────────────────────────────────────────
        remuxed = 0
        if self._auto_remux and self.remux_engine.is_available:
            pairs, remuxed = self._run_pre_remux(pairs)

        # ── Collision guard ───────────────────────────────────────────────────
        # Scan all pairs for duplicate (folder, new_name) — this catches
        # manually paired tracks that share a sanitized name (e.g. two "War"
        # files on disc 1 and disc 2 both becoming War.flac).
        # Disambiguate by prefixing with disc number (multi-disc) or track number.
        from collections import Counter
        name_counts = Counter((folder, new) for folder, _, new, _, _ in pairs)
        seen        = {}   # (folder, new) → count of times seen so far

        resolved = []
        for folder, old, new, tnum, dnum in pairs:
            key = (folder, new)
            if name_counts[key] > 1:
                seen[key] = seen.get(key, 0) + 1
                stem, ext = os.path.splitext(new)
                prefix    = f"Disc {dnum} - " if dnum > 1 else f"{tnum:02d} - "
                new       = f"{prefix}{stem}{ext}"
            resolved.append((folder, old, new, tnum, dnum))

        pairs = resolved

        try:
            for folder, old, new, tnum, dnum in pairs:
                if old == new:
                    continue
                old_p, new_p = os.path.join(folder, old), os.path.join(folder, new)
                if os.path.exists(old_p):
                    os.rename(old_p, new_p)
                    history.append((new_p, old_p))
                    renamed += 1
        except Exception as e:
            messagebox.showerror("Rename Error", str(e))
            return
        self.rename_history = history

        do_art   = self.apply_art.get()
        do_tags  = self.apply_tags.get()
        do_genre = self.apply_genre.get()

        if (do_art or do_tags or do_genre) and self.current_metadata:
            tag_errors = []

            # Build per-folder metadata so both single-album and batch use
            # the same loop over `pairs` (which has post-remux filenames).
            folder_meta = {}
            if self.batch_data:
                for item in self.batch_data:
                    if not item.get("release"):
                        continue
                    m = self.engine.get_release_metadata(item["release"]["id"])
                    m["cover_art_bytes"] = \
                        self.engine.get_cover_art_bytes(item["release"]["id"])
                    folder_meta[item["path"]] = m
            else:
                m = dict(self.current_metadata)
                m["cover_art_bytes"] = self.current_art_bytes
                folder_meta[self.selected_album_path.get()] = m

            for folder_path, _, new, tnum, dnum in pairs:
                base = folder_meta.get(folder_path)
                if not base:
                    continue
                final_path = os.path.join(folder_path, new)
                if not os.path.exists(final_path):
                    continue
                track_meta = dict(base)
                track_meta["title"]        = os.path.splitext(new)[0]
                track_meta["track_number"] = tnum
                track_meta["disc_number"]  = dnum
                res = write_metadata(final_path, track_meta,
                                     do_art, do_tags, do_genre)
                if res is True:
                    tagged += 1
                else:
                    tag_errors.append(f"{new}: {res}")

            if tag_errors:
                messagebox.showwarning(
                    "Tag Warnings",
                    f"{len(tag_errors)} error(s):\n" + "\n".join(tag_errors[:10])
                )

        msg = []
        if remuxed: msg.append(f"Converted: {remuxed} files")
        if renamed: msg.append(f"Renamed:   {renamed} files")
        if tagged:  msg.append(f"Tagged:    {tagged} files")
        messagebox.showinfo("Done", "\n".join(msg) if msg else "No changes needed.")
        if not self.batch_data:
            self.preview_renames()

    # ── Undo ──────────────────────────────────────────────────────────────────

    def undo_rename(self):
        if not self.rename_history:
            return
        for new, old in self.rename_history:
            if os.path.exists(new):
                os.rename(new, old)
        self.rename_history = []
        messagebox.showinfo("Undo", "Reverted!")

    # ── Pre-execution remux ───────────────────────────────────────────────────

    def _run_pre_remux(self, pairs):
        """Remux any file whose extension isn't in the skip set, update
        old/new filenames in pairs to reflect the new extension.
        Returns (updated_pairs, remuxed_count)."""
        skip    = {".mp3", ".flac"}
        target  = self._auto_remux_target
        quality = self._auto_remux_quality
        del_src = self._auto_remux_del_src
        errors  = []
        updated = []
        remuxed = 0

        for folder_path, old, new, tnum, dnum in pairs:
            src_ext = os.path.splitext(old)[1].lower()
            if src_ext not in skip and src_ext in SUPPORTED_INPUT:
                src_path = os.path.join(folder_path, old)
                dst_name = os.path.splitext(old)[0] + target
                dst_path = os.path.join(folder_path, dst_name)
                if os.path.exists(src_path):
                    res = self.remux_engine.convert(src_path, dst_path,
                                                    quality=quality,
                                                    delete_source=del_src)
                    if res is True:
                        old = dst_name
                        new = os.path.splitext(new)[0] + target
                        remuxed += 1
                    else:
                        errors.append(f"{old}: {res}")
            updated.append((folder_path, old, new, tnum, dnum))

        if errors:
            messagebox.showwarning(
                "Pre-remux Warnings",
                f"{len(errors)} file(s) could not be converted:\n"
                + "\n".join(errors[:10])
            )
        return updated, remuxed

    # ── Convert dialog ────────────────────────────────────────────────────────

    def _show_convert_dialog(self):
        folder = self.selected_album_path.get()
        if not folder or not os.path.exists(folder):
            messagebox.showwarning("No Folder", "Select an album folder first.")
            return
        if not self.remux_engine.is_available:
            messagebox.showerror("FFmpeg Missing",
                "FFmpeg is not installed or not on PATH.\n\n"
                "Download it from ffmpeg.org and add it to your PATH.")
            return

        audio_exts = {".mp3", ".flac", ".m4a", ".aac", ".mp4",
                      ".ogg", ".oga", ".wav", ".opus", ".wma"}
        files = sorted(
            f for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
            and os.path.splitext(f)[1].lower() in audio_exts
        )
        if not files:
            messagebox.showinfo("No Audio Files",
                "No supported audio files found in this folder.")
            return

        c   = THEMES.get(self.current_theme.get(), THEMES["Dark"])
        win = tk.Toplevel(self.root)
        win.title("Convert Files")
        win.geometry("560x520")
        win.resizable(False, False)
        win.configure(bg=c["bg"])
        win.update_idletasks()
        win.grab_set()
        win.lift()
        win.focus_force()

        pad = tk.Frame(win, bg=c["bg"])
        pad.pack(fill="both", expand=True, padx=16, pady=14)

        # ── Format + quality row ──────────────────────────────────────────────
        opts_row = tk.Frame(pad, bg=c["bg"])
        opts_row.pack(fill="x", pady=(0, 8))

        tk.Label(opts_row, text="Convert to:", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 10)).pack(side="left")

        fmt_var = tk.StringVar(value=".flac")
        fmt_cb  = self._combo(opts_row, c,
                              values=sorted(SUPPORTED_OUTPUT),
                              width=100)
        fmt_cb.configure(variable=fmt_var)
        fmt_cb.pack(side="left", padx=(8, 20))

        tk.Label(opts_row, text="Quality:", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 10)).pack(side="left")
        quality_var = tk.StringVar(value="best")
        quality_cb  = self._combo(opts_row, c,
                                  values=["low", "medium", "high", "best"],
                                  width=100)
        quality_cb.configure(variable=quality_var)
        quality_cb.pack(side="left", padx=(8, 0))

        # ── Delete source checkbox ────────────────────────────────────────────
        del_var = tk.BooleanVar(value=False)
        tk.Checkbutton(pad, text="Delete source files after conversion",
                       variable=del_var, bg=c["bg"], fg=c["fg"],
                       selectcolor=c["entry"], activebackground=c["bg"],
                       activeforeground=c["fg"], font=("Segoe UI", 9)
                       ).pack(anchor="w", pady=(0, 8))

        tk.Frame(pad, height=1, bg=c["border"]).pack(fill="x", pady=(0, 8))

        # ── File list with checkboxes ─────────────────────────────────────────
        list_hdr = tk.Frame(pad, bg=c["bg"])
        list_hdr.pack(fill="x", pady=(0, 4))
        tk.Label(list_hdr, text="Files to convert:", bg=c["bg"], fg="#888",
                 font=("Segoe UI", 9, "bold")).pack(side="left")

        _all_selected = [True]
        sel_btn = tk.Button(list_hdr, text="Select None",
                            bg=c["btn"], fg=c["fg"], relief="flat",
                            activebackground=c["border"], activeforeground=c["fg"],
                            font=("Segoe UI", 8), padx=8, pady=2, cursor="hand2")
        sel_btn.pack(side="right")

        list_outer = tk.Frame(pad, bg=c["entry"],
                              highlightthickness=1, highlightbackground=c["border"])
        list_outer.pack(fill="both", expand=True)

        canvas  = tk.Canvas(list_outer, bg=c["entry"], highlightthickness=0)
        list_sb = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        inner   = tk.Frame(canvas, bg=c["entry"])
        win_id  = canvas.create_window((0, 0), window=inner, anchor="nw")

        canvas.configure(yscrollcommand=list_sb.set)

        def _on_inner_cfg(_):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_cfg(e):
            canvas.itemconfig(win_id, width=e.width)

        inner.bind("<Configure>", _on_inner_cfg)
        canvas.bind("<Configure>", _on_canvas_cfg)
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        list_sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        check_vars = []
        for fname in files:
            var = tk.BooleanVar(value=True)
            check_vars.append((fname, var))
            tk.Checkbutton(inner, text=fname, variable=var,
                           bg=c["entry"], fg=c["fg"],
                           selectcolor=c["btn"], activebackground=c["entry"],
                           activeforeground=c["fg"], anchor="w",
                           font=("Segoe UI", 9)
                           ).pack(fill="x", padx=8, pady=1)

        def _toggle_all():
            _all_selected[0] = not _all_selected[0]
            for _, v in check_vars:
                v.set(_all_selected[0])
            sel_btn.configure(text="Select None" if _all_selected[0] else "Select All")

        sel_btn.configure(command=_toggle_all)

        # ── Progress bar ──────────────────────────────────────────────────────
        tk.Frame(pad, height=1, bg=c["border"]).pack(fill="x", pady=(8, 4))

        prog_trough = tk.Frame(pad, bg=c["btn"], height=4)
        prog_trough.pack(fill="x")
        prog_fill = tk.Frame(prog_trough, bg=c["accent"], height=4)
        prog_fill.place(x=0, y=0, relheight=1.0, relwidth=0.0)

        status_lbl = tk.Label(pad, text="Ready", bg=c["bg"], fg="#555",
                              font=("Segoe UI", 9))
        status_lbl.pack(anchor="w", pady=(4, 0))

        # ── Footer buttons ────────────────────────────────────────────────────
        foot = tk.Frame(pad, bg=c["bg"])
        foot.pack(fill="x", pady=(10, 0))

        run_btn = tk.Button(foot, text="Convert",
                            bg=c["accent"], fg="#ffffff", relief="flat",
                            activebackground=c["accent"], activeforeground="#ffffff",
                            padx=16, pady=5, cursor="hand2",
                            font=("Segoe UI", 9, "bold"))
        run_btn.pack(side="right")
        tk.Button(foot, text="Cancel", command=win.destroy,
                  bg=c["btn"], fg=c["fg"], relief="flat",
                  activebackground=c["border"], activeforeground=c["fg"],
                  padx=14, pady=5, cursor="hand2").pack(side="right", padx=(0, 8))

        def start():
            selected = [(f, v) for f, v in check_vars if v.get()]
            if not selected:
                messagebox.showwarning("Nothing selected",
                    "Check at least one file.", parent=win)
                return
            run_btn.configure(state="disabled")
            threading.Thread(
                target=self._convert_worker,
                args=(selected, folder, fmt_var.get(),
                      quality_var.get(), del_var.get(),
                      prog_fill, status_lbl, win),
                daemon=True
            ).start()

        run_btn.configure(command=start)

    def _convert_worker(self, selected, folder, fmt, quality,
                        delete_src, prog_fill, status_lbl, win):
        total  = len(selected)
        errors = []

        for i, (fname, _) in enumerate(selected):
            src = os.path.join(folder, fname)
            dst = self.remux_engine.suggested_output_path(src, fmt)

            self.root.after(0, status_lbl.configure,
                            {"text": f"Converting {i + 1}/{total}: {fname}"})
            self.root.after(0, prog_fill.place,
                            {"relwidth": i / total})

            res = self.remux_engine.convert(src, dst, quality=quality,
                                            delete_source=delete_src)
            if res is not True:
                errors.append(f"{fname}: {res}")

        self.root.after(0, prog_fill.place, {"relwidth": 1.0})
        self.root.after(0, self._convert_done, errors, total, win)

    def _convert_done(self, errors, total, win):
        ok = total - len(errors)
        if errors:
            messagebox.showwarning(
                "Convert Complete",
                f"{ok}/{total} converted successfully.\n\n"
                + "\n".join(errors[:10]),
                parent=win,
            )
        else:
            messagebox.showinfo("Convert Complete",
                                f"All {total} file(s) converted successfully.",
                                parent=win)
        win.destroy()

    # ── Filesystem ────────────────────────────────────────────────────────────

    def browse_root(self):
        path = filedialog.askdirectory()
        if path:
            self.root_dir.set(path)
            self.refresh_artists()
            self._save_config()

    def refresh_artists(self):
        p = self.root_dir.get()
        if os.path.exists(p):
            artists = sorted([d for d in os.listdir(p)
                               if os.path.isdir(os.path.join(p, d))])
            self.artist_cb.configure(values=artists)
            if artists:
                self.artist_cb.set(artists[0])
                self.on_artist_select(None)

    def on_artist_select(self, _event):
        artist_name = self.artist_cb.get()
        if not artist_name:
            return
        p = os.path.join(self.root_dir.get(), artist_name)
        self.selected_artist_path.set(p)
        self._known_releases = []
        self.current_artist_id = None
        self._sidebar_rows = []
        if os.path.exists(p):
            albums = sorted([d for d in os.listdir(p)
                              if os.path.isdir(os.path.join(p, d))])
            self.album_cb.configure(values=albums)
            if albums:
                self.album_cb.set(albums[0])
        threading.Thread(
            target=self._auto_detect_artist_thread,
            args=(artist_name,), daemon=True
        ).start()

    def _auto_detect_artist_thread(self, artist_name):
        """Run auto-detect in background, then trigger album detect on main thread."""
        self.root.after(0, self._auto_detect_artist, artist_name)
        # on_album_select will be called once artist detect completes via
        # the album_cb being set above — but we need to wait for releases
        # to be loaded first, so album detect runs from _auto_detect_artist.
        album = self.album_cb.get()
        if album:
            # Poll until releases are loaded (max 15s)
            import time
            for _ in range(30):
                time.sleep(0.5)
                if getattr(self, "_known_releases", []):
                    self.root.after(0, self._auto_detect_album, album)
                    break

    def on_album_select(self, _event):
        album_name = self.album_cb.get()
        if not album_name:
            return
        self.selected_album_path.set(
            os.path.join(self.selected_artist_path.get(), album_name))
        # If releases already loaded, detect immediately; else the artist
        # detect thread will trigger it once ready
        if getattr(self, "_known_releases", []):
            threading.Thread(
                target=lambda: self.root.after(0, self._auto_detect_album, album_name),
                daemon=True
            ).start()

    def _set_status(self, text):
        self._set_status_dot("detect", text)

    def _write_preview(self, text):
        self._preview_text_mode = True
        if self._active_tab == "Preview":
            self._set_tab("Preview")   # re-pack in text mode
        self.preview_area.configure(state="normal")
        self.preview_area.delete("1.0", tk.END)
        self.preview_area.insert(tk.END, text)
        self.preview_area.configure(state="disabled")

    def _save_config(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump({
                    "path":                   self.root_dir.get(),
                    "theme":                  self.current_theme.get(),
                    "spotify_id":             self._spotify_id,
                    "spotify_secret":         self._spotify_secret,
                    "auto_remux":             self._auto_remux,
                    "auto_remux_target":      self._auto_remux_target,
                    "auto_remux_quality":     self._auto_remux_quality,
                    "auto_remux_delete_source": self._auto_remux_del_src,
                }, f, indent=4)
        except Exception:
            pass


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    MusicManagerApp(root)
    root.mainloop()

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    MusicManagerApp(root)
    root.mainloop()