"""
gui/widgets.py
Small reusable pieces: background tasks, status icons, elided labels, the
cover-art view and toast notifications.
"""

from PySide6.QtCore import (QObject, QPointF, QRectF, QRunnable, QSize, Qt,
                            QThreadPool, QTimer, Signal, Slot)
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QWidget)


# ── Background tasks ──────────────────────────────────────────────────────────

class _Relay(QObject):
    """Lives on the GUI thread; carries a worker's result back to it."""
    finished = Signal(object, object)
    progress = Signal(int, int, str)

    def __init__(self, on_done, on_progress):
        super().__init__()
        self._on_done, self._on_progress = on_done, on_progress
        self.finished.connect(self._deliver)
        self.progress.connect(self._report)

    @Slot(object, object)
    def _deliver(self, result, error):
        _live.discard(self)
        if self._on_done:
            self._on_done(result, error)

    @Slot(int, int, str)
    def _report(self, done, total, text):
        if self._on_progress:
            self._on_progress(done, total, text)


_live = set()


class _Job(QRunnable):
    def __init__(self, fn, relay, with_progress):
        super().__init__()
        self._fn, self._relay, self._with_progress = fn, relay, with_progress

    def run(self):
        try:
            if self._with_progress:
                result = self._fn(lambda d, t, s="": self._relay.progress.emit(d, t, s))
            else:
                result = self._fn()
            out = (result, None)
        except RuntimeError as e:
            if "deleted" in str(e):                  # app closed mid-task
                return
            out = (None, e)
        except Exception as e:                       # surfaced to on_done
            out = (None, e)
        try:
            self._relay.finished.emit(*out)
        except RuntimeError:                         # app closed mid-task
            pass


def run_async(fn, on_done=None, on_progress=None):
    """Run fn() on the thread pool; call on_done(result, error) on the GUI
    thread. With on_progress, fn receives a report(done, total, text)
    callable whose calls arrive at on_progress on the GUI thread."""
    relay = _Relay(on_done, on_progress)
    _live.add(relay)
    QThreadPool.globalInstance().start(_Job(fn, relay, on_progress is not None))


# ── Styling helpers ───────────────────────────────────────────────────────────

def repolish(w):
    """Re-apply the stylesheet after changing a dynamic property."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def set_prop(w, name, value):
    if w.property(name) != value:
        w.setProperty(name, value)
        repolish(w)


def status_icon(kind, pal, size=16):
    """Library status mark: 'done' ✓, 'attention' ●, anything else ○."""
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(2.5, 2.5, size - 5, size - 5)
    if kind == "done":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pal["success"]))
        p.drawEllipse(r)
        pen = QPen(QColor(pal["window"]), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        s = size / 16
        p.drawPolyline([QPointF(5.2 * s, 8.3 * s), QPointF(7.2 * s, 10.3 * s),
                        QPointF(10.9 * s, 6.1 * s)])
    elif kind == "attention":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pal["warning"]))
        p.drawEllipse(r.adjusted(1.5, 1.5, -1.5, -1.5))
    else:
        p.setPen(QPen(QColor(pal["faint"]), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
    p.end()
    return QIcon(pm)


def rounded(pix, size, radius):
    """Centre-crop `pix` to a square of `size` px with rounded corners."""
    dpr = 2
    out = QPixmap(size * dpr, size * dpr)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    if pix.isNull():
        return out
    scaled = pix.scaled(size * dpr, size * dpr, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    x = (scaled.width() / dpr - size) / 2
    y = (scaled.height() / dpr - size) / 2
    p.drawPixmap(QPointF(-x, -y), scaled)
    p.end()
    return out


def folder_icon(color, size=16):
    """A plain folder glyph drawn in `color`. Qt's standard folder icon comes
    from the desktop icon theme, which a Flatpak or bundled app may not have."""
    icon = QIcon()
    for scale in (1, 2):
        s = size * scale
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(scale)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        u = size / 16.0
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(1.5 * u, 3 * u, 6 * u, 3 * u), 1 * u, 1 * u)
        body = QPainterPath()
        body.addRoundedRect(QRectF(1.5 * u, 4.5 * u, 13 * u, 9 * u), 1.5 * u, 1.5 * u)
        p.drawPath(tab.united(body))
        p.end()
        icon.addPixmap(pm)
    return icon


def placeholder_art(size, pal, radius=8):
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(pal["raised"]))
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setPen(QColor(pal["faint"]))
    f = p.font()
    f.setPixelSize(int(size * 0.38))
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "♪")
    p.end()
    return pm


# ── Widgets ───────────────────────────────────────────────────────────────────

class ElidedLabel(QLabel):
    """Single-line label that shortens with '…' instead of widening."""

    def __init__(self, text="", parent=None, mode=Qt.ElideRight):
        super().__init__(text, parent)
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(20)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), self._mode, r.width())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment()) | Qt.AlignVCenter, text)


class ArtView(QWidget):
    """Square cover art that fills the available width."""

    def __init__(self, pal, parent=None):
        super().__init__(parent)
        self._pal = pal
        self._pix = QPixmap()
        self._text = ""
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumSize(120, 120)

    def set_palette(self, pal):
        self._pal = pal
        self.update()

    def set_pixmap(self, pix, text=""):
        self._pix = pix if pix is not None else QPixmap()
        self._text = text
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def sizeHint(self):
        return QSize(260, 260)

    def paintEvent(self, _e):
        side = min(self.width(), self.height())
        x = (self.width() - side) / 2
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._pix.isNull():
            p.drawPixmap(int(x), 0, placeholder_art(side, self._pal, 12))
            if self._text:
                p.setPen(QColor(self._pal["muted"]))
                p.drawText(QRectF(x, side * 0.68, side, side * 0.25),
                           Qt.AlignHCenter | Qt.AlignTop, self._text)
        else:
            p.drawPixmap(int(x), 0, rounded(self._pix, side, 12))


class Toast(QFrame):
    """Transient notification at the bottom-right of its parent, sitting just
    above `above` (e.g. an action bar) so it never covers those buttons."""

    def __init__(self, parent, above=None):
        super().__init__(parent)
        self._above = above
        self.setObjectName("Toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(12)
        self._label = QLabel()
        self._action = QPushButton()
        self._action.setProperty("variant", "small")
        self._action.hide()
        lay.addWidget(self._label)
        lay.addWidget(self._action)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self._cb = None
        self._action.clicked.connect(self._fire)
        self.hide()

    def show_message(self, text, action_text=None, action=None, ms=6000):
        self._label.setText(text)
        self._cb = action
        self._action.setVisible(bool(action_text))
        if action_text:
            self._action.setText(action_text)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _fire(self):
        self.hide()
        if self._cb:
            self._cb()

    def _place(self):
        par = self.parentWidget()
        bottom = par.height() - 14
        if self._above is not None and self._above.isVisible():
            bottom = self._above.geometry().top() - 14
        self.move(par.width() - self.width() - 20, bottom - self.height())

    def reposition(self):
        if self.isVisible():
            self._place()
