"""Modal dialogs styled like the export modal in the mockups."""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSpinBox, QWidget)

from ..adapters.base import OptionSpec, ToolAdapter
from ..core import export
from ..core.storage import ScanRecord
from . import fmt, icons, theme
from .widgets import Card, CheckBox, Toggle, button, hbox, label, rule, vbox


class _Dim(QWidget):
    """Darkens the main window while a modal is open."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.show()

    def paintEvent(self, _e) -> None:
        QPainter(self).fillRect(self.rect(), QColor(7, 9, 11, 179))


class ModalDialog(QDialog):
    """Frameless modal: title row with close button, body layout, action row."""

    def __init__(self, parent: QWidget | None, title: str, subtitle: str = "", width: int = 470) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self._dim: _Dim | None = None
        outer = vbox(self)
        self.card = Card(tone="modal", padding=24, spacing=0)
        self.card.setFixedWidth(width)
        outer.addWidget(self.card)
        head = hbox()
        self.title = label(title)
        self.title.setStyleSheet("font-size:18px; font-weight:600;")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(button("", "x", variant="icon", tooltip="Закрыть", on_click=self.reject))
        self.card.lay.addLayout(head)
        if subtitle:
            self.card.lay.addSpacing(4)
            self.card.lay.addWidget(label(subtitle, "sub", wrap=True))
        self.body = vbox(spacing=10)
        self.card.lay.addSpacing(16)
        self.card.lay.addLayout(self.body)
        self.actions = hbox(spacing=8)
        self.actions.addStretch(1)
        self.card.lay.addSpacing(22)
        self.card.lay.addLayout(self.actions)

    def add_action(self, text: str, icon_name: str | None = None, *, primary: bool = False, danger: bool = False,
                   slot=None) -> QPushButton:
        variant = "primary" if primary else ("danger" if danger else None)
        b = button(text, icon_name, variant=variant, on_click=slot)
        self.actions.addWidget(b)
        if primary:
            b.setDefault(True)
        return b

    def exec(self) -> int:  # noqa: A003
        host = self.parentWidget().window() if self.parentWidget() else None
        if host is not None:
            self._dim = _Dim(host.centralWidget() if hasattr(host, "centralWidget") else host)
            self.adjustSize()
            geo = host.geometry()
            self.move(geo.center().x() - self.width() // 2, geo.y() + max(80, geo.height() // 6))
        try:
            return super().exec()
        finally:
            if self._dim is not None:
                self._dim.deleteLater()
                self._dim = None

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)


def confirm(parent: QWidget, title: str, text: str, ok_text: str = "Удалить", *, danger: bool = False) -> bool:
    dlg = ModalDialog(parent, title, width=440)
    msg = label(text, "lead", wrap=True)
    dlg.body.addWidget(msg)
    dlg.add_action("Отмена", slot=dlg.reject)
    if danger:
        b = dlg.add_action(ok_text, danger=True, slot=dlg.accept)
        b.setStyleSheet("QPushButton { background:#3A1F25; border-color:#533039; color:#F1777B; }"
                        "QPushButton:hover { background:#4A252C; }")
    else:
        dlg.add_action(ok_text, primary=True, slot=dlg.accept)
    return dlg.exec() == QDialog.DialogCode.Accepted


# ----------------------------------------------------------------- export
REPORT_TITLES = {
    "email": "Проверка цифрового следа", "domain": "Анализ домена", "username": "Поиск профилей",
    "phone": "Проверка номера", "file": "Метаданные файла", "ip": "Анализ IP-адреса",
}


def reports_dir() -> Path:
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
    d = Path(docs) / "OSINT Hub" / "Отчёты"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(text: str) -> str:
    text = re.sub(r"[^\w.@+-]+", "_", text, flags=re.UNICODE).strip("._")
    return text[:60] or "scan"


class FormatOption(QPushButton):
    """Checkable card-like button: icon + title + subtitle."""

    def __init__(self, icon_name: str, title: str, sub: str) -> None:
        super().__init__()
        self.setProperty("variant", "format")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(64)
        lay = hbox(self, margins=(14, 10, 14, 10), spacing=10)
        self._icon = QLabel()
        self._icon_name = icon_name
        lay.addWidget(self._icon)
        col = vbox(spacing=0)
        self._title = label(title)
        self._title.setStyleSheet("font-weight:600;")
        col.addWidget(self._title)
        col.addWidget(label(sub, "sub", wrap=True))
        lay.addLayout(col, 1)
        for w in (self._icon, self._title):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for i in range(col.count()):
            col.itemAt(i).widget().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(self._sync)
        self._sync(False)

    def _sync(self, on: bool) -> None:
        self._icon.setPixmap(icons.pixmap(self._icon_name, theme.TEXT if on else theme.SUB, 18))
        self._title.setStyleSheet(f"font-weight:600; color:{theme.TEXT if on else theme.SUB};")


class ExportDialog(ModalDialog):
    """Mockup 10: format + sections, then a Save dialog."""

    def __init__(self, parent: QWidget, scan: ScanRecord, storage) -> None:
        total = sum(len(r.findings) for r in scan.results.values())
        super().__init__(parent, "Экспорт отчёта",
                         f"{fmt.target_display(scan.target, scan.target_type)} · {fmt.findings(total)}")
        self.scan, self.storage, self.total = scan, storage, total
        self.saved_path: Path | None = None

        self.body.addWidget(label("Формат", "sub"))
        row = hbox(spacing=10)
        self.json_btn = FormatOption("braces", "JSON", "Для машинной обработки")
        self.html_btn = FormatOption("file-code", "HTML", "Для просмотра и печати")
        group = QButtonGroup(self)
        for b in (self.json_btn, self.html_btn):
            group.addButton(b)
            row.addWidget(b, 1)
        self.html_btn.setChecked(True)
        self.body.addLayout(row)
        self.body.addSpacing(10)
        self.body.addWidget(label("Включить разделы", "sub"))
        self.c_summary = CheckBox("Сводка и сведения о скане", True)
        self.c_findings = CheckBox("Найденные записи и источники", True)
        self.c_meta = CheckBox("Метаданные и сырой вывод инструментов", True)
        self.c_log = CheckBox("Технический лог", False)
        for c in (self.c_summary, self.c_findings, self.c_meta, self.c_log):
            self.body.addWidget(c)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        self.body.addWidget(self.error)
        self.add_action("Отмена", slot=self.reject)
        self.add_action("Сохранить", "download", primary=True, slot=self._save)

    def _save(self) -> None:
        fmt_ = "json" if self.json_btn.isChecked() else "html"
        opts = export.ExportOptions(self.c_summary.isChecked(), self.c_findings.isChecked(),
                                    self.c_meta.isChecked(), self.c_log.isChecked())
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        default = reports_dir() / f"osinthub_{_safe_name(fmt.target_display(self.scan.target, self.scan.target_type))}_{stamp}.{fmt_}"
        filt = "HTML (*.html)" if fmt_ == "html" else "JSON (*.json)"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт", str(default), filt)
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != f".{fmt_}":
            p = p.with_suffix(f".{fmt_}")
        try:
            size = export.export(self.scan, p, fmt_, opts)
        except Exception as exc:
            self.error.setText(f"Не удалось сохранить: {exc}")
            self.error.show()
            return
        title = (f"{REPORT_TITLES.get(self.scan.target_type, 'Отчёт')} · "
                 f"{fmt.target_display(self.scan.target, self.scan.target_type)}")
        self.storage.add_report(self.scan.id, title, fmt_, str(p), size, self.total)
        self.saved_path = p
        self.accept()


# ----------------------------------------------------------------- tool options
class _Worker(QObject):
    done = Signal(bool, str)


class ToolOptionsDialog(ModalDialog):
    """Timeout + adapter-declared options (generated from ``OptionSpec``)."""

    def __init__(self, parent: QWidget, adapter: ToolAdapter, settings) -> None:
        super().__init__(parent, f"Параметры · {adapter.title}", adapter.description, width=520)
        self.adapter, self.settings = adapter, settings
        self._fields: dict[str, Any] = {}
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 24 * 3600)
        self.timeout.setSuffix(" с")
        self.timeout.setValue(adapter.timeout())
        self._row("Таймаут", "Инструмент будет остановлен, если не уложится", self.timeout)
        for spec in adapter.options:
            self._fields[spec.key] = self._make(spec)
        if adapter.name == "sherlock":
            self._sherlock_update_row()
        self.add_action("Отмена", slot=self.reject)
        self.add_action("Сохранить", primary=True, slot=self._save)

    def _row(self, title: str, help_: str, widget: QWidget) -> None:
        row = hbox(spacing=16)
        col = vbox(spacing=2)
        col.addWidget(label(title))
        if help_:
            col.addWidget(label(help_, "sub", wrap=True))
        row.addLayout(col, 1)
        widget.setMinimumWidth(170 if not isinstance(widget, Toggle) else 34)
        row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(row)
        self.body.addWidget(rule())

    def _make(self, spec: OptionSpec) -> QWidget:
        value = self.adapter.option(spec.key)
        w: QWidget
        if spec.kind == "bool":
            w = Toggle(bool(value))
        elif spec.kind == "int":
            w = QSpinBox()
            w.setRange(spec.minimum if spec.minimum is not None else 0, spec.maximum if spec.maximum is not None else 10**6)
            w.setValue(int(value))
        elif spec.kind == "choice":
            w = QComboBox()
            for v, text in spec.choices:
                w.addItem(text, v)
            idx = max(0, w.findData(value))
            w.setCurrentIndex(idx)
        else:
            w = QLineEdit(str(value or ""))
            w.setProperty("role", "mono")
            w.setMinimumWidth(240)
        self._row(spec.label, spec.help, w)
        return w

    def _sherlock_update_row(self) -> None:
        from ..adapters.sherlock import update_site_data

        btn = button("Обновить базу сайтов", "download", size="sm")
        status = label("Загружает свежий список сайтов с sherlockproject.xyz", "sub", wrap=True)
        row = hbox(spacing=12)
        row.addWidget(status, 1)
        row.addWidget(btn)
        self.body.addLayout(row)
        worker = _Worker(self)

        def finished(ok: bool, text: str) -> None:
            btn.setEnabled(True)
            status.setText(text)
            status.setProperty("role", "sub" if ok else "error")
            theme.polish(status)

        worker.done.connect(finished)

        def run() -> None:
            btn.setEnabled(False)
            status.setText("Загрузка…")

            def job() -> None:
                try:
                    n = update_site_data()
                    worker.done.emit(True, f"База обновлена: {n} сайтов")
                except Exception as exc:
                    worker.done.emit(False, f"Не удалось обновить: {exc}")

            threading.Thread(target=job, daemon=True).start()

        btn.clicked.connect(run)

    def _save(self) -> None:
        name = self.adapter.name
        self.settings.set_tool_option(name, "timeout", self.timeout.value(), save=False)
        for key, w in self._fields.items():
            if isinstance(w, Toggle):
                v: Any = w.isChecked()
            elif isinstance(w, QSpinBox):
                v = w.value()
            elif isinstance(w, QComboBox):
                v = w.currentData()
            else:
                v = w.text().strip()
            self.settings.set_tool_option(name, key, v, save=False)
        self.settings.save()
        self.accept()


# ----------------------------------------------------------------- pick scan
class PickScanDialog(ModalDialog):
    """Choose a finished scan for a new report."""

    def __init__(self, parent: QWidget, storage) -> None:
        super().__init__(parent, "Новый отчёт", "Выберите скан, по которому нужно сформировать отчёт", width=520)
        self.selected: int | None = None
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFixedHeight(320)
        holder = QWidget()
        lay = vbox(holder, spacing=6)
        scans = [s for s in storage.list_scans(limit=100) if s.status in ("done", "error", "cancelled")]
        if not scans:
            lay.addWidget(label("Пока нет завершённых сканов.", "sub"))
        for s in scans:
            b = QPushButton(f"  {fmt.target_display(s.target, s.target_type)}    ·  {fmt.findings(s.findings_count)}  ·  "
                            f"{fmt.relative(s.created_at)}")
            b.setProperty("variant", "nav")
            b.setIcon(icons.icon(icons.TYPE_ICON.get(s.target_type, "search"), theme.SUB, 16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, sid=s.id: self._pick(sid))
            lay.addWidget(b)
        lay.addStretch(1)
        area.setWidget(holder)
        self.body.addWidget(area)
        self.add_action("Отмена", slot=self.reject)

    def _pick(self, scan_id: int) -> None:
        self.selected = scan_id
        self.accept()


def open_export(parent: QWidget, ctx, scan_id: int) -> None:
    """Show the export dialog for a scan and report the outcome with a toast."""
    scan = ctx.storage.get_scan(scan_id)
    if scan is None:
        ctx.toast("Скан не найден", "error")
        return
    dlg = ExportDialog(parent, scan, ctx.storage)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.saved_path:
        ctx.toast("Отчёт успешно экспортирован")
