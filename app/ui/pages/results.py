"""Mockup 06: scan results — summary, per-tool tabs, filterable table, raw output, related findings."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QComboBox, QFrame, QMenu, QPlainTextEdit, QScrollArea, QStackedWidget, QWidget

from ...adapters.holehe import HoleheAdapter
from ...core.related import Pivot, find_pivots
from ...core.schema import Finding, TargetType
from ...core.storage import ScanRecord
from .. import fmt, icons, theme
from ..dialogs import open_export
from ..findings_table import FindingsTable
from ..widgets import (Badge, Card, PageHeader, SearchField, TabStrip, button, clear_layout, hbox, icon_label, label, rule,
                       tool_button_menu, vbox)
from .base import Page

SUMMARY_ROWS = [("account", "Аккаунты", "user"), ("email", "Email", "at-sign"), ("phone", "Телефоны", "phone"),
                ("domain", "Домены", "globe"), ("geo+location", "Местоположения", "map-pin"),
                ("ip", "IP-адреса", "network"), ("url", "Ссылки", "link"), ("username", "Никнеймы", "user-search")]
DETAIL_PAGES = {"exiftool": "exif", "sherlock": "sherlock"}
PIVOT_WORDS = {
    TargetType.USERNAME: ("новый никнейм", "новых никнейма", "новых никнеймов"),
    TargetType.EMAIL: ("новый email", "новых email", "новых email"),
    TargetType.PHONE: ("новый телефон", "новых телефона", "новых телефонов"),
    TargetType.DOMAIN: ("новый домен", "новых домена", "новых доменов"),
    TargetType.IP: ("новый IP-адрес", "новых IP-адреса", "новых IP-адресов"),
}


class ResultsPage(Page):
    title = "Результаты"
    rail_key = "home"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, scroll=False, margins=(46, 44, 46, 30))
        self.scan: ScanRecord | None = None
        self.pivots: list[Pivot] = []

        self.header = PageHeader("Результат скана", "")
        self.type_badge = Badge("", "neutral")
        self.meta = label("", "sub")
        self.header.meta.addWidget(self.type_badge)
        self.header.meta.addWidget(self.meta)
        self.header.meta.addStretch(1)
        self.header.actions.addWidget(button("Повторить", "rotate", on_click=self._rerun))
        self.header.actions.addWidget(button("Экспорт", "download", variant="primary", on_click=self._export))
        self.body.addWidget(self.header)
        self.body.addSpacing(28)

        main = hbox(spacing=22)
        self.body.addLayout(main, 1)

        # ---- summary
        side = vbox(spacing=12)
        self.summary = Card(padding=20, spacing=0)
        self.summary.setFixedWidth(254)
        self.summary.lay.addWidget(label("Сводка находок", "cardtitle"))
        self.summary.lay.addSpacing(19)
        self.total = label("0", "big")
        self.summary.lay.addWidget(self.total)
        self.summary.lay.addWidget(label("всего записей", "sub"))
        self.summary.lay.addSpacing(10)
        self.stat_box = vbox()
        self.summary.lay.addLayout(self.stat_box)
        side.addWidget(self.summary)
        self.tools_card = Card(padding=(20, 16, 20, 16), spacing=10)
        self.tools_card.setFixedWidth(254)
        side.addWidget(self.tools_card)
        side.addStretch(1)
        side_host = QWidget()
        side_host.setLayout(side)
        side_area = QScrollArea()
        side_area.setWidgetResizable(True)
        side_area.setFrameShape(QScrollArea.Shape.NoFrame)
        side_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_area.setWidget(side_host)
        side_area.setFixedWidth(264)
        main.addWidget(side_area)

        # ---- right panel
        right = vbox(spacing=0)
        main.addLayout(right, 1)
        self.tabs = TabStrip()
        self.tabs.changed.connect(self._on_tab)
        right.addWidget(self.tabs)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)

        # table view
        table_host = QWidget()
        tl = vbox(table_host, spacing=0)
        tl.addSpacing(18)
        bar = hbox(spacing=8)
        self.search = SearchField("Поиск по находкам")
        self.search.textChanged.connect(lambda t: self._apply_filters())
        bar.addWidget(self.search, 1)
        self.type_btn = tool_button_menu("Тип", "funnel")
        self.type_menu = QMenu(self.type_btn)
        self.type_btn.setMenu(self.type_menu)
        bar.addWidget(self.type_btn)
        self.conf_btn = tool_button_menu("Достоверность", "sliders")
        self.conf_menu = QMenu(self.conf_btn)
        self.conf_actions: dict[str, QAction] = {}
        for key, text in fmt.CONFIDENCE.items():
            act = self.conf_menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(True)
            act.toggled.connect(lambda _=False: self._apply_filters())
            self.conf_actions[key] = act
        self.conf_btn.setMenu(self.conf_menu)
        bar.addWidget(self.conf_btn)
        tl.addLayout(bar)
        tl.addSpacing(14)
        self.notice = Card(padding=(15, 12, 15, 12), spacing=11, horizontal=True)
        self.notice.hide()
        tl.addWidget(self.notice)
        self.table = FindingsTable()
        self.table.pivot_requested.connect(self._pivot_from_finding)
        tl.addWidget(self.table, 1)
        self.empty = label("", "sub")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        tl.addWidget(self.empty)
        self.hint = QFrame()
        self.hint.setProperty("hint", True)
        hl = hbox(self.hint, margins=(15, 11, 11, 11), spacing=11)
        hl.addWidget(icon_label("sparkles", "#D0CAFD", 17))
        self.hint_text = label("", "hinttext", wrap=True)
        hl.addWidget(self.hint_text, 1)
        self.hint_btn = button("Проверить", "arrow-right", size="sm", icon_right=True)
        self.hint_menu = QMenu(self.hint_btn)
        self.hint_btn.setMenu(self.hint_menu)
        hl.addWidget(self.hint_btn)
        tl.addSpacing(16)
        tl.addWidget(self.hint)
        self.stack.addWidget(table_host)

        # raw view
        raw_host = QWidget()
        rl = vbox(raw_host, spacing=12)
        rl.addSpacing(18)
        rbar = hbox(spacing=8)
        self.raw_tool = QComboBox()
        self.raw_tool.setMinimumWidth(220)
        self.raw_tool.currentIndexChanged.connect(self._render_raw)
        rbar.addWidget(self.raw_tool)
        rbar.addStretch(1)
        rbar.addWidget(button("Копировать", "copy", on_click=self._copy_raw))
        rl.addLayout(rbar)
        self.raw = QPlainTextEdit()
        self.raw.setProperty("role", "raw")
        self.raw.setReadOnly(True)
        self.raw.setFont(theme.mono_font(12))
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        rl.addWidget(self.raw, 1)
        self.stack.addWidget(raw_host)

        ctx.bridge.scan_finished.connect(self._maybe_reload)
        ctx.bridge.run_status.connect(lambda sid, tool, d: self._maybe_reload(sid, d))

    # ------------------------------------------------------------ load
    def on_enter(self, scan_id: int | None = None, tab: str | None = None, **kwargs) -> None:
        if scan_id is not None:
            self.load(scan_id)
        elif self.scan is not None:
            self.load(self.scan.id, keep_tab=True)
        if tab:
            self.tabs.set_current(tab)
            self._on_tab(tab)

    def _maybe_reload(self, scan_id: int, _data: dict) -> None:
        if self.scan is not None and scan_id == self.scan.id and self.isVisible():
            self.load(scan_id, keep_tab=True)

    def load(self, scan_id: int, keep_tab: bool = False) -> None:
        scan = self.ctx.storage.get_scan(scan_id)
        if scan is None:
            self.ctx.toast("Скан не найден — возможно, он удалён", "error")
            self.ctx.go("history")
            return
        prev_tab = self.tabs.current() if keep_tab else None
        self.scan = scan
        self.header.eyebrow.setText(f"РЕЗУЛЬТАТ СКАНА #{scan.id:04d}")
        self.header.title.setText(fmt.target_display(scan.target, scan.target_type))
        self.type_badge.set(fmt.target_label(scan.target_type), "neutral")
        meta = fmt.long_date(scan.created_at)
        if scan.finished_at:
            meta += f"  ·  Длительность {fmt.duration(scan.created_at, scan.finished_at)}"
        if self.ctx.engine.is_active(scan.id):
            meta += "  ·  идёт сканирование"
        self.meta.setText(meta)

        rows: list[tuple[str, Finding]] = [(t, f) for t, r in scan.results.items() for f in r.findings]
        self.table.set_rows(rows)
        self._fill_summary(rows)
        self._fill_tools(scan)
        self._fill_type_menu(rows)

        self.tabs.clear()
        self.tabs.add_tab("all", f"Все {len(rows)}")
        for tool, res in scan.results.items():
            a = self.ctx.adapter(tool)
            title = a.title if a else tool
            suffix = " · ошибка" if res.status == "error" and not res.findings else f" {len(res.findings)}"
            self.tabs.add_tab(tool, f"{title}{suffix}")
        self.tabs.add_tab("raw", "Сырой вывод")
        self.raw_tool.blockSignals(True)
        self.raw_tool.clear()
        for tool in scan.results:
            a = self.ctx.adapter(tool)
            self.raw_tool.addItem(a.title if a else tool, tool)
        self.raw_tool.blockSignals(False)

        self._compute_pivots()
        tab = prev_tab if prev_tab and (prev_tab in scan.results or prev_tab in ("all", "raw")) else "all"
        self.tabs.set_current(tab)
        self._on_tab(tab)

    def _fill_summary(self, rows: list[tuple[str, Finding]]) -> None:
        clear_layout(self.stat_box)
        self.total.setText(str(len(rows)))
        counts: dict[str, int] = {}
        for _, f in rows:
            counts[f.type] = counts.get(f.type, 0) + 1
        shown = 0
        for key, text, ic in SUMMARY_ROWS:
            n = sum(counts.get(k, 0) for k in key.split("+"))
            if shown >= 5 and not n:
                continue
            shown += 1
            line = QWidget()
            line.setMinimumHeight(42)
            ll = hbox(line, spacing=10)
            ll.addWidget(icon_label(ic, theme.SUB, 15))
            ll.addWidget(label(text), 1)
            c = label(str(n))
            c.setStyleSheet("font-weight:600;")
            ll.addWidget(c)
            self.stat_box.addWidget(line)
            self.stat_box.addWidget(rule())
        other = len(rows) - sum(counts.get(k, 0) for key, _, _ in SUMMARY_ROWS for k in key.split("+"))
        if other:
            line = QWidget()
            line.setMinimumHeight(42)
            ll = hbox(line, spacing=10)
            ll.addWidget(icon_label("info", theme.SUB, 15))
            ll.addWidget(label("Прочее"), 1)
            ll.addWidget(label(str(other)))
            self.stat_box.addWidget(line)
        elif self.stat_box.count():
            item = self.stat_box.takeAt(self.stat_box.count() - 1)
            if item.widget():
                item.widget().deleteLater()

    def _fill_tools(self, scan: ScanRecord) -> None:
        clear_layout(self.tools_card.lay)
        self.tools_card.lay.addWidget(label("Инструменты", "cardtitle"))
        for tool, res in scan.results.items():
            a = self.ctx.adapter(tool)
            row = hbox(spacing=8)
            row.addWidget(label(a.title if a else tool), 1)
            text, variant = fmt.STATUS.get(res.status, (res.status, "neutral"))
            b = Badge(text, variant)
            if res.error:
                b.setToolTip(res.error)
            row.addWidget(b)
            self.tools_card.lay.addLayout(row)

    def _fill_type_menu(self, rows: list[tuple[str, Finding]]) -> None:
        self.type_menu.clear()
        self.type_actions: dict[str, QAction] = {}
        present = sorted({f.type for _, f in rows}, key=lambda t: list(fmt.FINDING_LABELS).index(t)
                         if t in fmt.FINDING_LABELS else 99)
        all_act = self.type_menu.addAction("Показать все")
        all_act.triggered.connect(lambda: self._set_all_types(True))
        self.type_menu.addSeparator()
        for t in present:
            act = self.type_menu.addAction(fmt.FINDING_LABELS.get(t, t))
            act.setCheckable(True)
            act.setChecked(True)
            act.toggled.connect(lambda _=False: self._apply_filters())
            self.type_actions[t] = act
        self.type_btn.setText("Тип")

    def _set_all_types(self, on: bool) -> None:
        for act in self.type_actions.values():
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)
        self._apply_filters()

    # ------------------------------------------------------------ tabs / filters
    def _on_tab(self, key: str) -> None:
        if key == "raw":
            self.stack.setCurrentIndex(1)
            self._render_raw()
            return
        self.stack.setCurrentIndex(0)
        self.table.proxy.update(tool=None if key == "all" else key)
        self._render_notice(key)
        self._apply_filters()

    def _apply_filters(self) -> None:
        types = {t for t, a in getattr(self, "type_actions", {}).items() if a.isChecked()}
        all_types = len(types) == len(getattr(self, "type_actions", {}))
        confs = {c for c, a in self.conf_actions.items() if a.isChecked()}
        self.table.proxy.update(text=self.search.text().strip(), types=None if all_types else types,
                                confidences=None if len(confs) == 3 else confs)
        hidden = len(getattr(self, "type_actions", {})) - len(types)
        self.type_btn.setText(f"Тип · {len(types)}" if hidden else "Тип")
        self.conf_btn.setText("Достоверность" if len(confs) == 3 else f"Достоверность · {len(confs)}")
        n = self.table.visible_count()
        self.table.setVisible(n > 0)
        self.empty.setVisible(n == 0)
        if n == 0:
            any_rows = bool(self.table.model_.rows)
            self.empty.setText("Ничего не найдено по текущим фильтрам" if any_rows else "Инструменты ничего не нашли")
            self.empty.setContentsMargins(0, 40, 0, 40)

    def _render_notice(self, key: str) -> None:
        clear_layout(self.notice.lay)
        self.notice.set_state(None)
        if self.scan is None or key not in self.scan.results:
            self.notice.hide()
            return
        res = self.scan.results[key]
        shown = False
        if res.status in ("error", "cancelled"):
            self.notice.set_state("error")
            self.notice.lay.addWidget(icon_label("circle-alert", theme.ERROR_SOFT, 17))
            self.notice.lay.addWidget(label(res.error or "Ошибка", "error", wrap=True), 1)
            self.notice.lay.addWidget(button("Повторить", "rotate", size="sm",
                                             on_click=lambda: self._retry(key)))
            shown = True
        elif key == "holehe" and isinstance(res.raw, dict):
            st = HoleheAdapter.stats(res.raw)
            self.notice.lay.addWidget(icon_label("info", theme.SUB, 17))
            self.notice.lay.addWidget(label(
                f"Проверено сервисов: {st['checked']} · найдено регистраций: {st['found']} · "
                f"не удалось проверить (лимиты/ошибки): {st['unchecked']}", "sub", wrap=True), 1)
            shown = True
        if key in DETAIL_PAGES and res.raw:
            if not shown:
                self.notice.lay.addWidget(icon_label("sparkles", theme.SUB, 17))
                text = "Карта и карточки метаданных" if key == "exiftool" else "Карточки найденных профилей"
                self.notice.lay.addWidget(label(text, "sub"), 1)
            self.notice.lay.addWidget(button("Подробный вид", "arrow-right", size="sm", icon_right=True,
                                             on_click=lambda: self.ctx.go(DETAIL_PAGES[key], scan_id=self.scan.id)))
            shown = True
        self.notice.setVisible(shown)

    def _render_raw(self) -> None:
        if self.scan is None:
            return
        tool = self.raw_tool.currentData()
        res = self.scan.results.get(tool) if tool else None
        if res is None:
            self.raw.setPlainText("")
            return
        if isinstance(res.raw, dict) and isinstance(res.raw.get("stdout"), str):
            text = res.raw["stdout"]
        else:
            text = json.dumps(res.raw, ensure_ascii=False, indent=2, default=str) if res.raw is not None else ""
        log = self.scan.runs.get(tool).log if tool in self.scan.runs else ""
        if not text:
            text = "Нет сырого вывода." + (f"\n\nЛог:\n{log}" if log else "")
        self.raw.setPlainText(text[:2_000_000])

    def _copy_raw(self) -> None:
        QGuiApplication.clipboard().setText(self.raw.toPlainText())
        self.ctx.toast("Скопировано в буфер обмена")

    # ------------------------------------------------------------ related findings
    def _compute_pivots(self) -> None:
        scan = self.scan
        assert scan is not None
        try:
            ttype = TargetType(scan.target_type)
        except ValueError:
            self.hint.hide()
            return
        self.pivots = find_pivots(scan.target, ttype, scan.results.values(), self.ctx.tools_map(),
                                  exclude=self.ctx.scan_chain_targets(scan.id),
                                  default_region=self.ctx.settings.get("default_region"))
        self.hint_menu.clear()
        if not self.pivots:
            self.hint.hide()
            return
        kinds = {p.type for p in self.pivots}
        if len(kinds) == 1:
            t = next(iter(kinds))
            n = len(self.pivots)
            words = PIVOT_WORDS[t]
            tools = ", ".join(self.ctx.adapter(x).title for x in self.pivots[0].tools)
            noun = fmt.plural(n, *words)
            verb = "Найден" if n % 10 == 1 and n % 100 != 11 else "Найдено"
            self.hint_text.setText(f"{verb} {noun} — проверить через {tools}")
        else:
            self.hint_text.setText(f"Найдено {fmt.plural(len(self.pivots), 'связанный объект', 'связанных объекта', 'связанных объектов')}"
                                   " — проверить через другие инструменты")
        for p in self.pivots:
            tools = ", ".join(self.ctx.adapter(x).title for x in p.tools)
            act = self.hint_menu.addAction(icons.icon(icons.TYPE_ICON.get(p.type.value, "search"), theme.TEXT, 16),
                                           f"{fmt.target_display(p.value, p.type.value)}   →  {tools}")
            act.setToolTip("Источник: " + ", ".join(p.sources))
            act.triggered.connect(lambda _=False, pv=p: self._launch(pv))
        if len(self.pivots) > 1:
            self.hint_menu.addSeparator()
            self.hint_menu.addAction(f"Проверить все ({len(self.pivots)})", self._launch_all)
        self.hint.show()

    def _launch(self, p: Pivot) -> None:
        assert self.scan is not None
        self.ctx.start_scan(p.value, p.type, p.tools, parent_id=self.scan.id)

    def _launch_all(self) -> None:
        assert self.scan is not None
        n = 0
        for p in self.pivots:
            if self.ctx.start_scan(p.value, p.type, p.tools, parent_id=self.scan.id, open_page=False):
                n += 1
        self.ctx.toast(f"Запущено сканов: {n} — они в истории")

    def _pivot_from_finding(self, f: Finding) -> None:
        assert self.scan is not None
        from ...core import validation

        ttype = TargetType(f.type) if f.type in TargetType._value2member_map_ else None
        if ttype is None:
            return
        try:
            value = validation.normalize(f.value, ttype, default_region=self.ctx.settings.get("default_region"))
        except validation.ValidationError as exc:
            self.ctx.toast(str(exc), "error")
            return
        tools = self.ctx.tools_for(ttype)
        if not tools:
            self.ctx.toast("Нет доступных инструментов для этого типа", "error")
            return
        self.ctx.start_scan(value, ttype, tools, parent_id=self.scan.id)

    # ------------------------------------------------------------ actions
    def _retry(self, tool: str) -> None:
        assert self.scan is not None
        self.ctx.engine.retry(self.scan.id, tool)
        self.ctx.go("scan", scan_id=self.scan.id)

    def _rerun(self) -> None:
        if self.scan is not None:
            new_id = self.ctx.engine.rerun(self.scan.id)
            self.ctx.go("scan", scan_id=new_id)

    def _export(self) -> None:
        if self.scan is not None:
            open_export(self, self.ctx, self.scan.id)
