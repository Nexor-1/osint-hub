"""Findings table (mockup 06): model, filter proxy and painted delegates."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QPersistentModelIndex, QRectF,
                            QSortFilterProxyModel, Qt, QUrl, Signal)
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QMenu, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTableView)

from ..core.schema import Finding
from . import fmt, icons, theme

COLUMNS = ["Тип", "Значение", "Источник", "Достоверность", ""]
COL_TYPE, COL_VALUE, COL_SOURCE, COL_CONF, COL_LINK = range(5)
MONO_TYPES = {"email", "phone", "domain", "ip", "url", "geo", "username", "datetime"}
ROLE_FINDING = Qt.ItemDataRole.UserRole + 1
ROLE_TOOL = Qt.ItemDataRole.UserRole + 2


def finding_url(f: Finding) -> str | None:
    url = f.extra.get("url")
    if not url and f.type == "url":
        url = f.value
    if not url and f.type == "geo" and "lat" in f.extra:
        url = f"https://www.openstreetmap.org/?mlat={f.extra['lat']}&mlon={f.extra['lon']}#map=16/{f.extra['lat']}/{f.extra['lon']}"
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return url
    return None


class FindingsModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, Finding]] = []

    def set_rows(self, rows: list[tuple[str, Finding]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        tool, f = self.rows[index.row()]
        col = index.column()
        if role == ROLE_FINDING:
            return f
        if role == ROLE_TOOL:
            return tool
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_TYPE:
                return fmt.FINDING_LABELS.get(f.type, f.type)
            if col == COL_VALUE:
                return f.value
            if col == COL_SOURCE:
                return f.source
            if col == COL_CONF:
                return fmt.CONFIDENCE.get(f.confidence, f.confidence)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_VALUE:
                field = f.extra.get("field")
                title = f.extra.get("title")
                parts = [f.value] + ([f"Поле: {field}"] if field else []) + ([title] if title else [])
                return "\n".join(parts)
            if col == COL_LINK and finding_url(f):
                return "Открыть в браузере"
        if role == Qt.ItemDataRole.FontRole and col == COL_VALUE and f.type in MONO_TYPES:
            return theme.mono_font(13)
        if role == Qt.ItemDataRole.UserRole:  # sort keys
            if col == COL_CONF:
                return fmt.CONFIDENCE_ORDER.get(f.confidence, 9)
            return str(self.data(index, Qt.ItemDataRole.DisplayRole) or "").lower()
        return None


class FindingsFilter(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.types: set[str] | None = None
        self.confidences: set[str] | None = None
        self.tool: str | None = None
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def update(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex | QPersistentModelIndex) -> bool:
        model: FindingsModel = self.sourceModel()  # type: ignore[assignment]
        tool, f = model.rows[row]
        if self.tool and tool != self.tool:
            return False
        if self.types is not None and f.type not in self.types:
            return False
        if self.confidences is not None and f.confidence not in self.confidences:
            return False
        if self.text:
            hay = " ".join([f.value, f.source, str(f.extra.get("field", "")), str(f.extra.get("title", "")),
                            fmt.FINDING_LABELS.get(f.type, "")]).lower()
            return all(word in hay for word in self.text.lower().split())
        return True


class FindingsDelegate(QStyledItemDelegate):
    """Paints type badges, confidence dots and link icons."""

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        f: Finding = index.data(ROLE_FINDING)
        col = index.column()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if hovered or option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(option.rect, QColor(theme.HOVER))
        p.setPen(QColor(theme.BORDER))
        p.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        r = option.rect.adjusted(16 if col == 0 else 6, 0, -6, 0)
        if col == COL_TYPE:
            text = index.data()
            font = theme.ui_font(11)
            font.setWeight(font.Weight.DemiBold)
            fm = QFontMetrics(font)
            w = fm.horizontalAdvance(text) + 18
            badge = QRectF(r.x(), r.center().y() - 11, w, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#242833"))
            p.drawRoundedRect(badge, 6, 6)
            p.setPen(QColor(theme.SUB))
            p.setFont(font)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        elif col == COL_CONF:
            color = {"high": theme.SUCCESS, "medium": theme.WARNING}.get(f.confidence, theme.DISABLED)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(r.x(), r.center().y() - 3.5, 7, 7))
            p.setPen(QColor(theme.SUB))
            p.setFont(theme.ui_font(12))
            p.drawText(r.adjusted(14, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, index.data())
        elif col == COL_LINK:
            if finding_url(f):
                pm = icons.pixmap("arrow-up-right", theme.TEXT if hovered else theme.SUB, 16)
                p.drawPixmap(r.center().x() - 8, r.center().y() - 8, pm)
        else:
            font = index.data(Qt.ItemDataRole.FontRole) or theme.ui_font(14 if col == COL_VALUE else 13)
            p.setFont(font)
            p.setPen(QColor(theme.TEXT if col == COL_VALUE else theme.SUB))
            text = QFontMetrics(font).elidedText(index.data() or "", Qt.TextElideMode.ElideRight, r.width())
            p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            if col == COL_VALUE and f.extra.get("field") and f.extra.get("field") not in (index.data(),):
                pass
        p.restore()


class FindingsTable(QTableView):
    """QTableView configured like the mockup; emits ``pivot_requested`` from the context menu."""

    pivot_requested = Signal(object)  # Finding

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model_ = FindingsModel()
        self.proxy = FindingsFilter()
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self.setItemDelegate(FindingsDelegate(self))
        self.setMouseTracking(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(54)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(COL_CONF, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(COL_LINK, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_TYPE, 126)
        self.setColumnWidth(COL_SOURCE, 190)
        self.setColumnWidth(COL_CONF, 130)
        self.setColumnWidth(COL_LINK, 44)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.clicked.connect(self._clicked)
        self.doubleClicked.connect(self._double)
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)

    def set_rows(self, rows: list[tuple[str, Finding]]) -> None:
        self.model_.set_rows(rows)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # Keep "Значение" the widest column at any window width.
        w = self.viewport().width()
        self.setColumnWidth(COL_TYPE, 120 if w > 720 else 104)
        self.setColumnWidth(COL_CONF, 130 if w > 720 else 126)
        self.setColumnWidth(COL_LINK, 40)
        self.setColumnWidth(COL_SOURCE, max(110, min(220, int(w * 0.22))))

    def visible_count(self) -> int:
        return self.proxy.rowCount()

    def _finding(self, index: QModelIndex) -> Finding | None:
        return index.data(ROLE_FINDING) if index.isValid() else None

    def _clicked(self, index: QModelIndex) -> None:
        f = self._finding(index)
        if f and index.column() == COL_LINK:
            url = finding_url(f)
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def _double(self, index: QModelIndex) -> None:
        f = self._finding(index)
        if f:
            QGuiApplication.clipboard().setText(f.value)

    def _menu(self, pos) -> None:
        index = self.indexAt(pos)
        f = self._finding(index)
        if f is None:
            return
        menu = QMenu(self)
        menu.addAction(icons.icon("copy", theme.TEXT, 16), "Копировать значение",
                       lambda: QGuiApplication.clipboard().setText(f.value))
        url = finding_url(f)
        if url:
            menu.addAction(icons.icon("arrow-up-right", theme.TEXT, 16), "Открыть в браузере",
                           lambda: QDesktopServices.openUrl(QUrl(url)))
            menu.addAction(icons.icon("link", theme.TEXT, 16), "Копировать ссылку",
                           lambda: QGuiApplication.clipboard().setText(url))
        if f.type in ("email", "username", "phone", "domain", "ip") and not f.extra.get("masked"):
            menu.addSeparator()
            menu.addAction(icons.icon("sparkles", theme.TEXT, 16), "Проверить другими инструментами",
                           lambda: self.pivot_requested.emit(f))
        menu.exec(self.viewport().mapToGlobal(pos))
