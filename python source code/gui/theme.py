"""
gui/theme.py
Theme palettes and stylesheet loading.

Each theme is defined by six base colours. Everything else (surfaces, muted
text, selection, status colours) is derived from them, so a new theme only
needs those six values.

style.qss uses @token placeholders, which stylesheet() substitutes before
the result goes to setStyleSheet().
"""

from pathlib import Path

from PySide6.QtGui import QColor

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

_QSS = Path(__file__).with_name("style.qss")


def _mix(a, b, t):
    """Blend colour a toward b by t (0 → a, 1 → b)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red()   + (cb.red()   - ca.red())   * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue()  + (cb.blue()  - ca.blue())  * t)).name()


def _readable_on(color):
    c = QColor(color)
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return "#10131a" if lum > 0.6 else "#ffffff"


def palette(name):
    """Full token set for theme `name`."""
    b = THEMES.get(name, THEMES["Dark"])
    light = QColor(b["bg"]).lightnessF() > 0.5
    t = {
        "window":      b["bg"],
        "panel":       _mix(b["bg"], b["entry"], 0.55),
        "card":        b["entry"],
        "card_hover":  _mix(b["entry"], b["fg"], 0.06),
        "raised":      b["btn"],
        "raised_hover": _mix(b["btn"], b["fg"], 0.10),
        "border":      b["border"],
        "border_soft": _mix(b["border"], b["bg"], 0.45),
        "text":        b["fg"],
        "muted":       _mix(b["fg"], b["bg"], 0.42),
        "faint":       _mix(b["fg"], b["bg"], 0.62),
        "accent":      b["accent"],
        "accent_hover": _mix(b["accent"], "#ffffff", 0.12),
        "accent_text": _readable_on(b["accent"]),
        "selection":   _mix(b["accent"], b["bg"], 0.72),
        "selection_text": b["fg"] if not light else "#10131a",
        "success":     "#1f9d55" if light else "#3ecf8e",
        "warning":     "#b7791f" if light else "#f0a03c",
        "danger":      "#c53030" if light else "#ef6461",
    }
    t["success_bg"] = _mix(t["success"], b["bg"], 0.85)
    t["warning_bg"] = _mix(t["warning"], b["bg"], 0.85)
    t["danger_bg"]  = _mix(t["danger"],  b["bg"], 0.86)
    return t


def stylesheet(name):
    qss = _QSS.read_text(encoding="utf-8")
    # Longest tokens first so @card_hover isn't clobbered by @card.
    for k, v in sorted(palette(name).items(), key=lambda kv: -len(kv[0])):
        qss = qss.replace("@" + k, v)
    return qss
