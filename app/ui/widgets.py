"""Reusable widgets implementing the components of the design system screen."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Property,
                            Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from . import icons, theme


# ---------------------------------------------------------------- layout helpers
def vbox(parent: QWidget | None = None, *, margins: Sequence[int] = (0, 0, 0, 0), spacing: int = 0) -> QVBoxLayout:
    lay = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def hbox(parent: QWidget | None = None, *, margins: Sequence[int] = (0, 0, 0, 0), spacing: int = 0) -> QHBoxLayout:
    lay = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def clear_layout(layout: QLayout) -> None:
    """Remove and delete every item of ``layout`` (recursively)."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def label(text: str = "", role: str | None = None, *, wrap: bool = False, selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setCursor(Qt.CursorShape.IBeamCursor)
    return lbl


def eyebrow(text: str) -> QLabel:
    lbl = label(text.upper(), "eyebrow")
    f = theme.ui_font(12, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
    lbl.setFont(f)
    return lbl


def rule() -> QFrame:
    r = QFrame()
    r.setProperty("rule", True)
    r.setFixedHeight(1)
    return r


def icon_label(name: str, color: str = theme.SUB, size: int = 16) -> QLabel:
    lbl = QLabel()
    lbl.setPixmap(icons.pixmap(name, color, size))
    lbl.setFixedSize(size, size)
    return lbl


class Card(QFrame):
    """Rounded surface (``.card`` in the mockups)."""

    def __init__(self, parent: QWidget | None = None, *, hoverable: bool = False, tone: str | None = None,
                 padding: Sequence[int] | int = 0, spacing: int = 0, horizontal: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        if hoverable:
            self.setProperty("hoverable", True)
        if tone:
            self.setProperty("tone", tone)
        pad = (padding,) * 4 if isinstance(padding, int) else tuple(padding)
        self.lay = (hbox if horizontal else vbox)(self, margins=pad, spacing=spacing)

    def set_state(self, state: str | None) -> None:
        theme.set_prop(self, "state", state)


class Badge(QLabel):
    """Status pill: neutral | muted | success | warn | error | active."""

    def __init__(self, text: str = "", variant: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("badge", variant)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set(self, text: str, variant: str) -> None:
        self.setText(text)
        theme.set_prop(self, "badge", variant)
        self.adjustSize()


def button(text: str = "", icon_name: str | None = None, *, variant: str | None = None, size: str | None = None,
           icon_right: bool = False, tooltip: str = "", on_click: Callable[[], None] | None = None,
           parent: QWidget | None = None) -> QPushButton:
    """Push button styled by variant: None (secondary) | primary | text | danger | icon | chip."""
    btn = QPushButton(text, parent)
    if variant:
        btn.setProperty("variant", variant)
    if size:
        btn.setProperty("size", size)
    if icon_name:
        color = {"primary": "#FFFFFF", "danger": "#F1777B", "text": theme.SUB}.get(variant or "", theme.TEXT)
        if variant == "icon":
            color = theme.SUB
        btn.setIcon(icons.icon(icon_name, color, 16, theme.TEXT if variant in ("icon", "text") else None))
        btn.setIconSize(QSize(16, 16))
        if icon_right:
            btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    if variant == "icon":
        btn.setFixedSize(30, 30)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        btn.clicked.connect(lambda _=False: on_click())
    return btn


class Toggle(QAbstractButton):
    """34×20 switch from the design system."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(34, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self) -> QSize:
        return QSize(34, 20)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor("#343943"), QColor(theme.ACCENT)
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 34, 20), 10, 10)
        knob = QColor("#FFFFFF") if self._pos > 0.5 else QColor("#A6ABB4")
        if not self.isEnabled():
            knob.setAlpha(140)
        p.setBrush(knob)
        p.drawEllipse(QRectF(3 + 14 * self._pos, 3, 14, 14))


class CheckBox(QAbstractButton):
    """17px rounded checkbox with a label (``.check`` in the mockups)."""

    def __init__(self, text: str = "", checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(17 + (12 + fm.horizontalAdvance(self.text()) if self.text() else 0), max(22, fm.height()))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - 17) / 2
        box = QRectF(0.5, y + 0.5, 16, 16)
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(box, 5, 5)
            p.drawPixmap(int(box.x() + 2), int(box.y() + 2), icons.pixmap("check", "#FFFFFF", 12, 2.6))
        else:
            p.setPen(QPen(QColor("#6D7280"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 5, 5)
        if self.text():
            p.setPen(QColor(theme.TEXT if self.isEnabled() else theme.DISABLED))
            p.setFont(self.font())
            p.drawText(self.rect().adjusted(29, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self.text())


class ProgressLine(QWidget):
    """2px progress bar; ``None`` value = indeterminate (animated segment)."""

    COLORS = {"accent": theme.ACCENT, "success": theme.SUCCESS, "error": theme.ERROR, "warn": theme.WARNING}

    def __init__(self, value: float | None = 0.0, variant: str = "accent", height: int = 2,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self._value: float | None = value
        self._variant = variant
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._sync_timer()

    def set_value(self, value: float | None, variant: str | None = None) -> None:
        self._value = value
        if variant:
            self._variant = variant
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        if self._value is None and not self._timer.isActive():
            self._timer.start()
        elif self._value is not None and self._timer.isActive():
            self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.3
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#30343C"))
        color = QColor(self.COLORS.get(self._variant, theme.ACCENT))
        if self._value is None:
            seg = w * 0.3
            x = (self._phase - 0.3) * w
            p.fillRect(QRectF(max(0, x), 0, min(seg, w - max(0, x)) + min(0, x), h), color)
        else:
            p.fillRect(QRectF(0, 0, w * max(0.0, min(1.0, self._value)), h), color)


class ToolIcon(QWidget):
    """36px tinted rounded square with a tool icon."""

    def __init__(self, icon_name: str, tint: str = "violet", size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._tint = icon_name, tint
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        bg, fg = theme.TINTS.get(self._tint, theme.TINTS["violet"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        s = self.width()
        p.drawRoundedRect(QRectF(0, 0, s, s), s / 4, s / 4)
        isz = int(s * 0.53)
        p.drawPixmap((s - isz) // 2, (s - isz) // 2, icons.pixmap(self._icon, fg, isz))


class SiteLogo(QLabel):
    """Letter tile for a site (Sherlock profile cards)."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        letters = "".join(ch for ch in name if ch.isalnum())[:2] or "?"
        super().__init__(letters[0].upper() + letters[1:].lower(), parent)
        self.setProperty("role", "sitelogo")
        self.setFixedSize(35, 35)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class Dot(QWidget):
    def __init__(self, color: str = theme.SUCCESS, size: int = 7, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(self.rect())


class ElidedLabel(QLabel):
    """Single-line label that elides with "…" instead of growing."""

    def __init__(self, text: str = "", role: str | None = None, mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self._mode = mode
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        self.setToolTip(text if len(text) > 40 else "")
        self._update()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update()

    def _update(self) -> None:
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, self._mode, max(10, self.width())))


class ResponsiveGrid(QWidget):
    """Grid that reflows its items into as many columns as fit ``min_col`` px."""

    def __init__(self, min_col: int = 200, max_cols: int = 5, spacing: int = 12, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min_col, self._max_cols = min_col, max_cols
        self._items: list[QWidget] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)

    def set_items(self, items: Iterable[QWidget]) -> None:
        for w in self._items:
            self._grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._items = list(items)
        for w in self._items:
            w.setParent(self)
        self._cols = 0
        self._relayout(force=True)

    def append_items(self, items: Iterable[QWidget]) -> None:
        """Add items without recreating the existing ones (pagination)."""
        new = list(items)
        for w in new:
            w.setParent(self)
        self._items.extend(new)
        self._relayout(force=True)

    def items(self) -> list[QWidget]:
        return list(self._items)

    def columns(self) -> int:
        return max(1, self._cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, force: bool = False) -> None:
        width = self.width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().width()
        sp = self._grid.spacing()
        cols = max(1, min(self._max_cols, (width + sp) // (self._min_col + sp)))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w in self._items:
            self._grid.removeWidget(w)
        for i, w in enumerate(self._items):
            self._grid.addWidget(w, i // cols, i % cols)
        for c in range(self._max_cols):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
            self._grid.setColumnMinimumWidth(c, 0)
        for w in self._items:
            w.show()


class Segmented(QFrame):
    """Segmented control (Sherlock: «Только найденные / Все проверенные»)."""

    changed = Signal(int)

    def __init__(self, labels: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("segmented", True)
        lay = hbox(self, margins=(4, 4, 4, 4), spacing=2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        for i, text in enumerate(labels):
            b = button(text, variant="segment")
            b.setCheckable(True)
            self._group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        if self.buttons:
            self.buttons[0].setChecked(True)
        self._group.idClicked.connect(self.changed.emit)

    def set_label(self, index: int, text: str) -> None:
        self.buttons[index].setText(text)

    def current(self) -> int:
        return self._group.checkedId()

    def set_current(self, index: int) -> None:
        self.buttons[index].setChecked(True)


class TabStrip(QWidget):
    """Underlined text tabs with a bottom rule."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = vbox(self)
        self._row = hbox(spacing=2)
        outer.addLayout(self._row)
        outer.addWidget(rule())
        self._row.addStretch(1)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

    def add_tab(self, key: str, text: str) -> QPushButton:
        b = button(text, variant="tab")
        b.setCheckable(True)
        b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self._group.addButton(b)
        self._row.insertWidget(self._row.count() - 1, b)
        self._buttons[key] = b
        if len(self._buttons) == 1:
            b.setChecked(True)
        return b

    def clear(self) -> None:
        for b in self._buttons.values():
            self._group.removeButton(b)
            b.setParent(None)
            b.deleteLater()
        self._buttons.clear()

    def set_text(self, key: str, text: str) -> None:
        if key in self._buttons:
            self._buttons[key].setText(text)

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def current(self) -> str | None:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return None


class Toast(QFrame):
    """Transient notification in the top-right corner of its parent."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("toast", True)
        lay = hbox(self, margins=(14, 10, 14, 10), spacing=9)
        self._icon = QLabel()
        self._text = label("", "toast")
        lay.addWidget(self._icon)
        lay.addWidget(self._text)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(220)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, kind: str = "success", ms: int = 3200) -> None:
        theme.set_prop(self, "toast", True if kind == "success" else "error")
        color = theme.SUCCESS if kind == "success" else theme.ERROR_SOFT
        self._icon.setPixmap(icons.pixmap("circle-check" if kind == "success" else "circle-alert", color, 16))
        self._text.setText(text)
        self.adjustSize()
        self.reposition()
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity() if self.isVisible() else 0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent:
            self.move(QPoint(parent.width() - self.width() - 44, 24))

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self) -> None:
        self._anim.finished.disconnect(self._hide_once)
        if self._fx.opacity() < 0.05:
            self.hide()


class SearchField(QFrame):
    """Input with a leading search icon (QLineEdit actions misalign under QSS padding)."""

    def __init__(self, placeholder: str = "", icon_name: str = "search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("inputbox", True)
        lay = hbox(self, margins=(12, 0, 6, 0), spacing=8)
        lay.addWidget(icon_label(icon_name, theme.SUB, 16))
        self.edit = QLineEdit()
        self.edit.setProperty("role", "bare")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit, 1)
        self.textChanged = self.edit.textChanged

    def eventFilter(self, obj, e) -> bool:
        from PySide6.QtCore import QEvent

        if e.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            theme.set_prop(self, "focused", e.type() == QEvent.Type.FocusIn)
        return False

    def text(self) -> str:
        return self.edit.text()

    def clear(self) -> None:
        self.edit.clear()

    def blockSignals(self, b: bool) -> bool:  # noqa: N802
        return self.edit.blockSignals(b)


class PageHeader(QWidget):
    """Eyebrow + title (+ lead / meta) on the left, actions on the right."""

    def __init__(self, eyebrow_text: str, title: str, lead: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = hbox(self, spacing=16)
        left = vbox(spacing=6)
        self.eyebrow = eyebrow(eyebrow_text)
        self.title = label(title, "pagetitle")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left.addWidget(self.eyebrow)
        left.addWidget(self.title)
        self.lead = label(lead or "", "lead", wrap=True)
        self.lead.setVisible(bool(lead))
        left.addSpacing(2)
        left.addWidget(self.lead)
        self.meta = hbox(spacing=8)
        left.addLayout(self.meta)
        filler = QWidget()
        filler.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        filler.setFixedHeight(0)
        left.addWidget(filler)
        row.addLayout(left, 1)
        self.actions = hbox(spacing=8)
        row.addLayout(self.actions)
        row.setAlignment(self.actions, Qt.AlignmentFlag.AlignTop)

    def set_lead(self, text: str) -> None:
        self.lead.setText(text)
        self.lead.setVisible(bool(text))


class SectionHeader(QWidget):
    def __init__(self, title: str, right: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = hbox(self)
        self.title = label(title, "section")
        row.addWidget(self.title)
        row.addStretch(1)
        if right is not None:
            row.addWidget(right)


class EmptyState(Card):
    """Illustration + text + optional action (history "Ничего не найдено")."""

    def __init__(self, eyebrow_text: str, title: str, text: str, action: QPushButton | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, tone="subtle", padding=22, spacing=25, horizontal=True)
        art = QLabel()
        art.setPixmap(icons.render_svg(icons.EMPTY_ILLUSTRATION, 140, 120))
        art.setFixedSize(150, 130)
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(art)
        col = vbox(spacing=6)
        col.addStretch(1)
        col.addWidget(eyebrow(eyebrow_text))
        self.title = label(title, "cardtitle")
        self.text = label(text, "sub", wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.text)
        if action is not None:
            col.addSpacing(8)
            row = hbox()
            row.addWidget(action)
            row.addStretch(1)
            col.addLayout(row)
        col.addStretch(1)
        self.lay.addLayout(col, 1)


class KeyValueGrid(QWidget):
    """Two-column key/value list (ExifTool cards)."""

    def __init__(self, key_width: int = 137, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)
        self._grid.setColumnMinimumWidth(0, key_width)
        self._grid.setColumnStretch(1, 1)
        self._rows = 0

    def add(self, key: str, value: str, *, mono: bool = False) -> None:
        k = label(key, "sub")
        v = label(value, "mono" if mono else None, wrap=True, selectable=True)
        if not mono:
            v.setStyleSheet("font-size:12px;")
        self._grid.addWidget(k, self._rows, 0, Qt.AlignmentFlag.AlignTop)
        self._grid.addWidget(v, self._rows, 1, Qt.AlignmentFlag.AlignTop)
        self._rows += 1

    def clear(self) -> None:
        clear_layout(self._grid)
        self._rows = 0

    def count(self) -> int:
        return self._rows


def tool_button_menu(text: str, icon_name: str) -> QToolButton:
    """Toolbar button that opens a menu (filters in results/history)."""
    tb = QToolButton()
    tb.setText(text)
    tb.setIcon(icons.icon(icon_name, theme.TEXT, 16))
    tb.setIconSize(QSize(16, 16))
    tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    tb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    tb.setCursor(Qt.CursorShape.PointingHandCursor)
    tb.setStyleSheet("QToolButton::menu-indicator { image: none; width:0; }")
    return tb


def rounded_pixmap_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path
