"""Mockup 09: scan history with search, filters, reopen, re-run and delete."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QFrame, QMenu, QWidget

from ...core.schema import TargetType
from .. import fmt, theme
from ..dialogs import confirm
from ..widgets import (Badge, Card, EmptyState, ElidedLabel, PageHeader, SearchField, button, clear_layout, hbox, icon_label,
                       label, tool_button_menu, vbox)
from .base import Page

COLS = [("Цель", 0), ("Тип", 112), ("Инструменты", 130), ("Дата", 128), ("Находки", 84), ("Действия", 104)]
PAGE = 100
DATE_FILTERS = [("Любая дата", None), ("Сегодня", 0), ("7 дней", 7), ("30 дней", 30)]


class HistoryRow(QFrame):
    def __init__(self, page: "HistoryPage", scan, last: bool) -> None:
        super().__init__()
        self.page, self.scan = page, scan
        ctx = page.ctx
        self.setProperty("tablerow", True)
        self.setProperty("clickable", True)
        if last:
            self.setProperty("last", True)
        self.setMinimumHeight(62)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = hbox(self, margins=(16, 0, 16, 0), spacing=10)
        target = ElidedLabel(fmt.target_display(scan.target, scan.target_type))
        target.setStyleSheet("font-weight:600;")
        target.setToolTip(scan.target)
        row.addWidget(target, 1)
        tcell = QWidget()
        tcell.setFixedWidth(COLS[1][1])
        tl = hbox(tcell)
        tl.addWidget(Badge(fmt.target_label(scan.target_type), "neutral"))
        tl.addStretch(1)
        row.addWidget(tcell)
        icell = QWidget()
        icell.setObjectName("toolsCell")
        icell.setFixedWidth(COLS[2][1])
        il = hbox(icell, spacing=5)
        for tool in scan.tools:
            a = ctx.adapter(tool)
            if a:
                ic = icon_label(a.icon, theme.SUB, 15)
                ic.setToolTip(a.title)
                il.addWidget(ic)
        il.addStretch(1)
        row.addWidget(icell)
        d = label(fmt.relative(scan.created_at), "sub")
        d.setFixedWidth(COLS[3][1])
        row.addWidget(d)
        fcell = QWidget()
        fcell.setFixedWidth(COLS[4][1])
        fl = hbox(fcell)
        if ctx.engine.is_active(scan.id):
            fl.addWidget(Badge("Идёт", "active"))
        elif scan.status == "error" and not scan.findings_count:
            fl.addWidget(Badge("Ошибка", "error"))
        else:
            n = label(str(scan.findings_count))
            n.setStyleSheet("font-weight:600;")
            fl.addWidget(n)
        fl.addStretch(1)
        row.addWidget(fcell)
        acell = QWidget()
        acell.setFixedWidth(COLS[5][1])
        al = hbox(acell, spacing=2)
        al.addWidget(button("", "arrow-up-right", variant="icon", tooltip="Открыть",
                            on_click=lambda: ctx.open_scan(scan.id)))
        al.addWidget(button("", "rotate", variant="icon", tooltip="Запустить повторно",
                            on_click=lambda: page.rerun(scan.id)))
        al.addWidget(button("", "trash", variant="icon", tooltip="Удалить",
                            on_click=lambda: page.delete(scan.id)))
        al.addStretch(1)
        row.addWidget(acell)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.page.ctx.open_scan(self.scan.id)


class HistoryPage(Page):
    title = "История"
    rail_key = "history"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, margins=(60, 48, 60, 40))
        self.limit = PAGE
        self.body.addWidget(PageHeader("Архив исследований", "История", "Ранее выполненные сканы и их результаты."))
        self.body.addSpacing(28)

        bar = hbox(spacing=8)
        self.search = SearchField("Поиск по цели")
        bar.addWidget(self.search, 1)
        self.type_btn = tool_button_menu("Все типы", "funnel")
        tmenu = QMenu(self.type_btn)
        self.type_group = QActionGroup(tmenu)
        for text, value in [("Все типы", None)] + [(t.label, t.value) for t in TargetType]:
            act = tmenu.addAction(text)
            act.setCheckable(True)
            act.setData(value)
            act.setChecked(value is None)
            self.type_group.addAction(act)
        self.type_group.triggered.connect(lambda a: self._filter_changed())
        self.type_btn.setMenu(tmenu)
        bar.addWidget(self.type_btn)
        self.date_btn = tool_button_menu("Любая дата", "calendar")
        dmenu = QMenu(self.date_btn)
        self.date_group = QActionGroup(dmenu)
        for text, days in DATE_FILTERS:
            act = dmenu.addAction(text)
            act.setCheckable(True)
            act.setData(days)
            act.setChecked(days is None)
            self.date_group.addAction(act)
        self.date_group.triggered.connect(lambda a: self._filter_changed())
        self.date_btn.setMenu(dmenu)
        bar.addWidget(self.date_btn)
        self.body.addLayout(bar)
        self.body.addSpacing(18)

        self.table = Card()
        head = QFrame()
        head.setProperty("tablehead", True)
        head.setFixedHeight(40)
        hl = hbox(head, margins=(16, 0, 16, 0), spacing=10)
        for i, (text, width) in enumerate(COLS):
            lbl = label(text, "sub")
            if i == 2:
                lbl.setObjectName("toolsCell")
            if width:
                lbl.setFixedWidth(width)
                hl.addWidget(lbl)
            else:
                hl.addWidget(lbl, 1)
        self.table.lay.addWidget(head)
        self.rows_host = QWidget()
        self.rows = vbox(self.rows_host)
        self.table.lay.addWidget(self.rows_host)
        self.body.addWidget(self.table)
        self.more_btn = button("Показать ещё", on_click=self._more)
        self.body.addSpacing(12)
        mrow = hbox()
        mrow.addStretch(1)
        mrow.addWidget(self.more_btn)
        mrow.addStretch(1)
        self.body.addLayout(mrow)

        self.empty_filter = EmptyState("Состояние фильтра", "Ничего не найдено",
                                       "Ни один скан не подходит под запрос и фильтры. Измените условия поиска "
                                       "или сбросьте фильтры.",
                                       button("Сбросить фильтры", on_click=self.reset_filters))
        self.empty_all = EmptyState("История", "Сканов пока нет",
                                    "Запустите первый скан на главной — результаты появятся здесь.",
                                    button("На главную", "arrow-right", icon_right=True,
                                           on_click=lambda: ctx.go("home")))
        self.body.addSpacing(25)
        self.body.addWidget(self.empty_filter)
        self.body.addWidget(self.empty_all)
        self.body.addStretch(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _t: self._filter_changed(debounce=True))
        ctx.bridge.history_changed.connect(lambda: self.refresh() if self.isVisible() else None)

    def on_enter(self, **kwargs) -> None:
        self.refresh()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._sync_columns()

    def _sync_columns(self) -> None:
        # Narrow windows: drop the tool icons column to keep targets readable.
        show = self.width() >= 1050
        for w in self.table.findChildren(QWidget, "toolsCell"):
            w.setVisible(show)

    def _filter_changed(self, debounce: bool = False) -> None:
        self.limit = PAGE
        t = self.type_group.checkedAction()
        self.type_btn.setText(t.text() if t else "Все типы")
        d = self.date_group.checkedAction()
        self.date_btn.setText(d.text() if d else "Любая дата")
        if debounce:
            self._debounce.start()
        else:
            self.refresh()

    def reset_filters(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.type_group.actions()[0].setChecked(True)
        self.date_group.actions()[0].setChecked(True)
        self._filter_changed()

    def _since(self) -> str | None:
        act = self.date_group.checkedAction()
        days = act.data() if act else None
        if days is None:
            return None
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
        return start.astimezone(timezone.utc).isoformat(timespec="seconds")

    def refresh(self) -> None:
        act = self.type_group.checkedAction()
        ttype = act.data() if act else None
        query = self.search.text().strip()
        scans = self.ctx.storage.list_scans(query, ttype, self._since(), limit=self.limit + 1)
        has_more = len(scans) > self.limit
        scans = scans[:self.limit]
        clear_layout(self.rows)
        for i, s in enumerate(scans):
            self.rows.addWidget(HistoryRow(self, s, i == len(scans) - 1))
        self._sync_columns()
        filtered = bool(query or ttype or self._since())
        self.table.setVisible(bool(scans))
        self.more_btn.setVisible(has_more)
        self.empty_filter.setVisible(not scans and filtered)
        self.empty_all.setVisible(not scans and not filtered)

    def _more(self) -> None:
        self.limit += PAGE
        self.refresh()

    def rerun(self, scan_id: int) -> None:
        new_id = self.ctx.engine.rerun(scan_id)
        self.ctx.go("scan", scan_id=new_id)

    def delete(self, scan_id: int) -> None:
        if self.ctx.engine.is_active(scan_id):
            self.ctx.toast("Скан ещё выполняется — сначала остановите его", "error")
            return
        rec = self.ctx.storage.get_scan(scan_id, with_results=False)
        name = fmt.target_display(rec.target, rec.target_type) if rec else f"#{scan_id}"
        if confirm(self, "Удалить скан?", f"Скан «{name}» и все его находки будут удалены из истории. "
                                          "Экспортированные файлы отчётов останутся на диске.", danger=True):
            self.ctx.storage.delete_scan(scan_id)
            self.ctx.toast("Скан удалён")
            self.refresh()
