"""Mockup 05: live scan — per-tool cards, overall progress and a live log."""

from __future__ import annotations

import html
import re
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from ...core.schema import Status
from .. import fmt, icons, theme
from ..widgets import (Badge, Card, PageHeader, ProgressLine, ResponsiveGrid, Toggle, ToolIcon, button, hbox,
                       icon_label, label, rule, vbox)
from .base import Page

LEVEL_TAG = {"run": ("RUN", theme.ACCENT_SOFT), "found": ("FOUND", theme.SUCCESS), "done": ("DONE", theme.ACCENT_SOFT),
             "error": ("ERROR", "#F17B7F"), "warn": ("WARN", theme.WARNING), "info": ("INFO", "#949AA7"),
             "start": ("START", theme.ACCENT_SOFT), "wait": ("WAIT", theme.ACCENT_SOFT)}
_TAG_RE = re.compile(r"^\[(\w+)\]\s*")


class ScanCard(Card):
    def __init__(self, ctx, scan_id: int, tool: str) -> None:
        super().__init__(padding=17, spacing=0)
        self.ctx, self.scan_id, self.tool = ctx, scan_id, tool
        a = ctx.adapter(tool)
        self.setMinimumHeight(138)
        top = hbox(spacing=12)
        top.addWidget(ToolIcon(a.icon, a.accent))
        col = vbox(spacing=2)
        col.addWidget(label(a.title, "tiletitle"))
        col.addWidget(label(a.description, "sub"))
        top.addLayout(col, 1)
        self.badge = Badge("В очереди", "neutral")
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        self.lay.addLayout(top)
        self.lay.addSpacing(14)
        self.note = label("Ожидает запуска", "sub", wrap=True)
        self.lay.addWidget(self.note)
        self.lay.addStretch(1)
        self.bar = ProgressLine(0.0)
        self.lay.addSpacing(12)
        self.lay.addWidget(self.bar)
        foot = hbox(spacing=8)
        self.lay.addSpacing(10)
        self.lay.addLayout(foot)
        self.detail = label("", "sub")
        foot.addWidget(self.detail, 1)
        self.retry = button("Повторить", "rotate", size="sm", on_click=self._retry)
        self.stop = button("Стоп", "square", variant="text", size="sm", on_click=self._stop)
        foot.addWidget(self.stop)
        foot.addWidget(self.retry)
        self.retry.hide()
        self.stop.hide()
        self.fraction: float | None = 0.0
        self.status = Status.QUEUED.value

    def _retry(self) -> None:
        self.ctx.engine.retry(self.scan_id, self.tool)
        self.set_status(Status.QUEUED.value)

    def _stop(self) -> None:
        self.ctx.engine.cancel(self.scan_id, self.tool)

    def set_status(self, status: str, error: str | None = None, findings: int | None = None) -> None:
        self.status = status
        self.retry.setVisible(status in (Status.ERROR.value, Status.CANCELLED.value))
        self.stop.setVisible(status == Status.RUNNING.value)
        self.set_state(None)
        if status == Status.QUEUED.value:
            self.badge.set("В очереди", "neutral")
            self.note.setProperty("role", "sub")
            self.note.setText("Ожидает запуска")
            self.bar.set_value(0.0, "accent")
            self.fraction = 0.0
        elif status == Status.RUNNING.value:
            self.badge.set("Идёт", "active")
            self.note.setProperty("role", "sub")
            if self.note.text() in ("Ожидает запуска", ""):
                self.note.setText("Выполняется…")
            self.bar.set_value(None if self.fraction in (None, 0.0) else self.fraction, "accent")
        elif status == Status.DONE.value:
            n = findings or 0
            self.badge.set(f"Найдено {n}" if n else "Ничего не найдено", "success" if n else "muted")
            self.note.setProperty("role", "sub")
            self.bar.set_value(1.0, "success")
            self.fraction = 1.0
        elif status == Status.ERROR.value:
            self.badge.set("Ошибка", "error")
            self.note.setProperty("role", "error")
            self.note.setText(error or "Инструмент не отвечает")
            self.bar.set_value(1.0 if findings else 0.0, "error")
            self.set_state("error")
            self.fraction = 1.0
            if findings:
                self.detail.setText(f"Сохранено частичных находок: {findings}")
        elif status == Status.CANCELLED.value:
            self.badge.set("Остановлено", "warn")
            self.note.setProperty("role", "sub")
            self.note.setText(error or "Остановлено пользователем")
            self.bar.set_value(self.fraction or 0.0, "warn")
            self.fraction = 1.0
        theme.polish(self.note)

    def set_progress(self, fraction: float | None, note: str) -> None:
        if self.status != Status.RUNNING.value:
            return
        self.fraction = fraction
        self.bar.set_value(fraction, "accent")
        if note:
            self.note.setText(note)

    def set_finished_detail(self, started: str | None, finished: str | None) -> None:
        if self.status == Status.DONE.value:
            self.note.setText(f"Проверка завершена · {fmt.duration(started, finished)}")


class LogPanel(Card):
    def __init__(self, on_collapse) -> None:
        super().__init__(tone="log")
        self.setFixedWidth(332)
        head = QWidget()
        head.setFixedHeight(56)
        hl = hbox(head, margins=(17, 0, 10, 0), spacing=10)
        hl.addWidget(icon_label("terminal", theme.TEXT, 16))
        hl.addWidget(label("Живой лог", "cardtitle"))
        hl.addStretch(1)
        hl.addWidget(button("", "panel-right", variant="icon", tooltip="Скрыть лог", on_click=on_collapse))
        self.lay.addWidget(head)
        self.lay.addWidget(rule())
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setFont(theme.mono_font(11))
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.view.document().setDocumentMargin(14)
        self.lay.addWidget(self.view, 1)
        self.lay.addWidget(rule())
        foot = QWidget()
        foot.setFixedHeight(45)
        fl = hbox(foot, margins=(17, 0, 17, 0), spacing=8)
        fl.addWidget(label("Автопрокрутка", "sub"))
        fl.addStretch(1)
        self.autoscroll = Toggle(True)
        fl.addWidget(self.autoscroll)
        self.lay.addWidget(foot)

    def clear(self) -> None:
        self.view.clear()

    def append(self, time: str, level: str, message: str, tool_title: str = "") -> None:
        m = _TAG_RE.match(message)
        tag, color = LEVEL_TAG.get(level, LEVEL_TAG["info"])
        if m:
            tag = m.group(1).upper()
            message = message[m.end():]
        if tool_title and tool_title.lower() not in message.lower():
            message = f"{tool_title} · {message}"
        msg_color = {"found": theme.SUCCESS, "error": "#F17B7F", "done": "#A99CFB"}.get(level, "#949AA7")
        line = (f'<span style="color:#5A5F69">{html.escape(time)}</span>&nbsp;&nbsp;'
                f'<span style="color:{color}">[{html.escape(tag)}]</span>&nbsp;'
                f'<span style="color:{msg_color}">{html.escape(message)}</span>')
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.view.appendHtml(line)
        if self.autoscroll.isChecked() or at_bottom:
            self.view.moveCursor(QTextCursor.MoveOperation.End)
            bar.setValue(bar.maximum())


class ScanPage(Page):
    title = "Сканирование"
    rail_key = "home"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, scroll=False, margins=(60, 48, 60, 40))
        self.scan_id: int | None = None
        self.cards: dict[str, ScanCard] = {}

        self.header = PageHeader("Активная задача", "Сканирование")
        self.meta_icon = icon_label("search", theme.SUB, 16)
        self.meta_text = label("", "lead")
        self.header.meta.addWidget(self.meta_icon)
        self.header.meta.addWidget(self.meta_text)
        self.header.meta.addStretch(1)
        self.stop_btn = button("Остановить", "square", on_click=self._stop_all)
        self.results_btn = button("Открыть результаты", "arrow-right", variant="primary", icon_right=True,
                                  on_click=self._open_results)
        self.log_btn = button("Лог", "terminal", variant="text", on_click=lambda: self._set_log_visible(True))
        self.header.actions.addWidget(self.log_btn)
        self.header.actions.addWidget(self.stop_btn)
        self.header.actions.addWidget(self.results_btn)
        self.body.addWidget(self.header)
        self.body.addSpacing(30)

        main = hbox(spacing=24)
        self.body.addLayout(main, 1)
        left_scroll_host = QWidget()
        left = vbox(left_scroll_host, spacing=16)
        from PySide6.QtWidgets import QScrollArea

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(left_scroll_host)
        main.addWidget(area, 1)

        overall = Card(padding=23, spacing=0)
        row = hbox()
        col = vbox(spacing=4)
        col.addWidget(label("Общий прогресс", "section"))
        self.counts = label("", "sub")
        col.addWidget(self.counts)
        row.addLayout(col, 1)
        self.pct = label("0%", "pct")
        row.addWidget(self.pct, 0, Qt.AlignmentFlag.AlignTop)
        overall.lay.addLayout(row)
        overall.lay.addSpacing(16)
        self.overall_bar = ProgressLine(0.0)
        overall.lay.addWidget(self.overall_bar)
        left.addWidget(overall)
        self.grid = ResponsiveGrid(min_col=300, max_cols=2, spacing=12)
        left.addWidget(self.grid)
        left.addStretch(1)

        self.log = LogPanel(lambda: self._set_log_visible(False))
        main.addWidget(self.log)
        self._set_log_visible(True)

        ctx.bridge.run_status.connect(self._on_status)
        ctx.bridge.progress.connect(self._on_progress)
        ctx.bridge.log.connect(self._on_log)
        ctx.bridge.scan_finished.connect(self._on_finished)

    # ------------------------------------------------------------ lifecycle
    def on_enter(self, scan_id: int | None = None, **kwargs) -> None:
        if scan_id is None or scan_id == self.scan_id:
            return
        self.scan_id = scan_id
        rec = self.ctx.storage.get_scan(scan_id, with_results=False)
        if rec is None:
            self.ctx.go("home")
            return
        self.meta_icon.setPixmap(icons.pixmap(icons.TYPE_ICON.get(rec.target_type, "search"), theme.SUB, 16))
        meta = f"{fmt.target_display(rec.target, rec.target_type)}  ·  {fmt.target_label(rec.target_type)}"
        if rec.parent_id:
            meta += f"  ·  связанный объект из скана #{rec.parent_id:04d}"
        self.meta_text.setText(meta)
        self.cards = {t: ScanCard(self.ctx, scan_id, t) for t in rec.tools}
        self.grid.set_items(self.cards.values())
        self.log.clear()
        now = datetime.now().strftime("%H:%M:%S")
        self.log.append(now, "start", f"Создана задача #{scan_id:04d} · {fmt.target_display(rec.target, rec.target_type)}")
        self.log.append(now, "info", f"Тип цели: {fmt.target_label(rec.target_type)}")
        for tool, run in rec.runs.items():
            self.cards[tool].set_status(run.status, run.error, run.findings_count)
            # Replay the buffered log of runs that are already in progress.
            for line in self.ctx.engine.run_log(scan_id, tool):
                m = re.match(r"(\S+) \[(\w+)\] (.*)", line)
                if m:
                    self.log.append(m.group(1), m.group(2).lower(), m.group(3))
        active = self.ctx.engine.is_active(scan_id)
        self.stop_btn.setVisible(active)
        self.results_btn.setVisible(not active)
        self._update_overall()

    # ------------------------------------------------------------ engine events
    def _on_status(self, scan_id: int, tool: str, data: dict) -> None:
        if scan_id != self.scan_id:
            return
        if tool not in self.cards:  # tool added by a retry from elsewhere
            self.cards[tool] = ScanCard(self.ctx, scan_id, tool)
            self.grid.set_items(list(self.cards.values()))
        card = self.cards[tool]
        status = data.get("status", "")
        card.set_status(status, data.get("error"), data.get("findings"))
        if status == Status.DONE.value:
            rec = self.ctx.storage.get_scan(scan_id, with_results=False)
            run = rec.runs.get(tool) if rec else None
            if run:
                card.set_finished_detail(run.started_at, run.finished_at)
        if status == Status.QUEUED.value:
            self.stop_btn.show()
            self.results_btn.hide()
            self.log.append(datetime.now().strftime("%H:%M:%S"), "wait",
                            f"{self.ctx.adapter(tool).title} поставлен в очередь")
        self._update_overall()

    def _on_progress(self, scan_id: int, tool: str, fraction, note: str) -> None:
        if scan_id == self.scan_id and tool in self.cards:
            self.cards[tool].set_progress(fraction, note)
            self._update_overall()

    def _on_log(self, scan_id: int, tool: str, data: dict) -> None:
        if scan_id == self.scan_id:
            a = self.ctx.adapter(tool)
            self.log.append(data["time"], data["level"], data["message"], a.title if a else tool)

    def _on_finished(self, scan_id: int, data: dict) -> None:
        if scan_id != self.scan_id:
            return
        self.stop_btn.hide()
        self.results_btn.show()
        status = data.get("status")
        n = data.get("findings", 0)
        self.log.append(datetime.now().strftime("%H:%M:%S"), "done", f"Скан завершён · {fmt.findings(n)}")
        self._update_overall()
        if self.isVisible():
            self.ctx.toast("Скан завершён" if status != "error" else "Скан завершён с ошибками",
                           "success" if status != "error" else "error")
            self.ctx.go("results", scan_id=scan_id)

    # ------------------------------------------------------------ helpers
    def _update_overall(self) -> None:
        cards = list(self.cards.values())
        if not cards:
            return
        done = sum(c.status in (Status.DONE.value, Status.ERROR.value, Status.CANCELLED.value) for c in cards)
        running = sum(c.status == Status.RUNNING.value for c in cards)
        queued = sum(c.status == Status.QUEUED.value for c in cards)
        total = 0.0
        for c in cards:
            if c.status == Status.RUNNING.value:
                total += c.fraction if c.fraction else 0.1
            elif c.status != Status.QUEUED.value:
                total += 1.0
        frac = total / len(cards)
        self.pct.setText(f"{int(frac * 100)}%")
        self.overall_bar.set_value(frac, "success" if done == len(cards) else "accent")
        self.counts.setText(f"{fmt.plural(done, 'завершён', 'завершено', 'завершено')} · "
                            f"{running} выполняется · {queued} ожидает" if queued == 1 else
                            f"{fmt.plural(done, 'завершён', 'завершено', 'завершено')} · "
                            f"{running} выполняется · {queued} ожидают")

    def _set_log_visible(self, visible: bool) -> None:
        self.log.setVisible(visible)
        self.log_btn.setVisible(not visible)

    def _stop_all(self) -> None:
        if self.scan_id is not None:
            self.ctx.engine.cancel(self.scan_id)
            self.log.append(datetime.now().strftime("%H:%M:%S"), "warn", "Остановка по запросу пользователя")

    def _open_results(self) -> None:
        if self.scan_id is not None:
            self.ctx.go("results", scan_id=self.scan_id)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # Narrow windows: the log collapses to a button to keep the cards readable.
        if self.width() < 1000 and self.log.isVisible():
            self._set_log_visible(False)
