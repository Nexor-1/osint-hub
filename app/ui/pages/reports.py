"""Mockup 10: exported reports."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QMenu

from .. import fmt, icons, theme
from ..dialogs import PickScanDialog, open_export, reports_dir
from ..widgets import Badge, Card, EmptyState, PageHeader, ResponsiveGrid, button, hbox, label
from .base import Page


class ReportCard(Card):
    def __init__(self, page: "ReportsPage", rep) -> None:
        super().__init__(padding=20, spacing=0)
        self.page, self.rep = page, rep
        self.setMinimumHeight(205)
        exists = Path(rep.path).exists()
        top = hbox()
        ic = QLabel()
        ic.setFixedSize(36, 36)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet("background:#24243A; border-radius:9px;")
        ic.setPixmap(icons.pixmap("file-code" if rep.format == "html" else "braces", "#AA9EFA", 19))
        top.addWidget(ic)
        top.addStretch(1)
        top.addWidget(Badge(rep.format.upper(), "neutral") if exists else Badge("Файл удалён", "error"),
                      0, Qt.AlignmentFlag.AlignTop)
        self.lay.addLayout(top)
        self.lay.addSpacing(20)
        title = label(rep.title, "cardtitle", wrap=True)
        self.lay.addWidget(title)
        self.lay.addSpacing(6)
        self.lay.addWidget(label(f"{fmt.findings(rep.findings_count)} · {fmt.long_date(rep.created_at, False)}", "sub"))
        self.lay.addStretch(1)
        bottom = hbox(spacing=6)
        bottom.addWidget(label(fmt.size(rep.size), "sub"), 1)
        open_btn = button("Открыть", "arrow-up-right", size="sm", on_click=self._open)
        open_btn.setEnabled(exists)
        bottom.addWidget(open_btn)
        more = button("", "ellipsis", variant="icon", tooltip="Ещё")
        more.setStyleSheet("QPushButton::menu-indicator { image:none; width:0; }")
        menu = QMenu(more)
        a = menu.addAction(icons.icon("folder-open", theme.TEXT, 16), "Показать в папке", self._reveal)
        a.setEnabled(exists)
        if rep.scan_id:
            menu.addAction(icons.icon("arrow-right", theme.TEXT, 16), "Открыть скан",
                           lambda: page.ctx.open_scan(rep.scan_id))
        menu.addSeparator()
        menu.addAction(icons.icon("trash", theme.TEXT, 16), "Убрать из списка", lambda: page.remove(rep.id))
        more.setMenu(menu)
        bottom.addWidget(more)
        self.lay.addLayout(bottom)

    def _open(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.rep.path))

    def _reveal(self) -> None:
        subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(self.rep.path)}"])


class ReportsPage(Page):
    title = "Отчёты"
    rail_key = "reports"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, margins=(60, 48, 60, 40))
        header = PageHeader("Сохранённые материалы", "Отчёты", "Экспортируйте результаты для дальнейшей работы.")
        header.actions.addWidget(button("Папка отчётов", "folder-open", variant="text",
                                        on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir())))))
        header.actions.addWidget(button("Новый отчёт", "plus", variant="primary", on_click=self._new))
        self.body.addWidget(header)
        self.body.addSpacing(30)
        self.grid = ResponsiveGrid(min_col=280, max_cols=3, spacing=14)
        self.body.addWidget(self.grid)
        self.empty = EmptyState("Отчёты", "Отчётов пока нет",
                                "Откройте результаты скана и нажмите «Экспорт» — или создайте отчёт здесь.",
                                button("Новый отчёт", "plus", on_click=self._new))
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

    def on_enter(self, **kwargs) -> None:
        self.refresh()

    def refresh(self) -> None:
        reps = self.ctx.storage.list_reports()
        self.grid.set_items([ReportCard(self, r) for r in reps])
        self.grid.setVisible(bool(reps))
        self.empty.setVisible(not reps)

    def _new(self) -> None:
        dlg = PickScanDialog(self, self.ctx.storage)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected:
            open_export(self, self.ctx, dlg.selected)
            self.refresh()

    def remove(self, report_id: int) -> None:
        self.ctx.storage.delete_report(report_id)
        self.refresh()
