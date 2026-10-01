"""Mockup 11: settings — general, tools, API keys, storage, about."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFrame, QLabel, QLineEdit, QScrollArea, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from ...config import APP_LICENSE, APP_REPO, APP_TITLE, APP_VERSION, SecretSpec, app_dir, data_dir, tools_dir
from .. import fmt, icons, theme
from ..dialogs import ToolOptionsDialog, confirm, reports_dir
from ..widgets import (Badge, Card, PageHeader, Toggle, ToolIcon, button, clear_layout, hbox, label, rule, vbox)
from .base import Page

SECTIONS = [("general", "Общие", "sliders"), ("tools", "Инструменты", "blocks"), ("keys", "API-ключи", "key"),
            ("storage", "Хранилище", "hard-drive"), ("about", "О программе", "info")]
REGIONS = [("RU", "Россия (+7)"), ("KZ", "Казахстан (+7)"), ("BY", "Беларусь (+375)"), ("UA", "Украина (+380)"),
           ("UZ", "Узбекистан (+998)"), ("AM", "Армения (+374)"), ("GE", "Грузия (+995)"), ("US", "США (+1)"),
           ("GB", "Великобритания (+44)"), ("DE", "Германия (+49)"), ("FR", "Франция (+33)"), ("TR", "Турция (+90)")]
LICENSES = {"exiftool": "GPL-3.0 / Artistic", "phoneinfoga": "GPL-3.0", "holehe": "GPL-3.0",
            "spiderfoot": "MIT", "sherlock": "MIT"}


def setting_row(title: str, desc: str, *widgets: QWidget, last: bool = False) -> QWidget:
    w = QWidget()
    w.setMinimumHeight(86)
    row = hbox(w, spacing=16)
    col = vbox(spacing=5)
    col.addStretch(1)
    col.addWidget(label(title))
    if desc:
        col.addWidget(label(desc, "sub", wrap=True))
    col.addStretch(1)
    row.addLayout(col, 1)
    for x in widgets:
        row.addWidget(x, 0, Qt.AlignmentFlag.AlignVCenter)
    holder = QWidget()
    hl = vbox(holder)
    hl.addWidget(w)
    if not last:
        hl.addWidget(rule())
    return holder


def section(title: str, lead: str, right: QWidget | None = None) -> tuple[QWidget, QVBoxLayout]:
    host = QWidget()
    lay = vbox(host, spacing=0)
    head = hbox()
    col = vbox(spacing=6)
    t = label(title)
    t.setStyleSheet("font-size:18px; font-weight:500;")
    col.addWidget(t)
    col.addWidget(label(lead, "sub", wrap=True))
    head.addLayout(col, 1)
    if right is not None:
        head.addWidget(right, 0, Qt.AlignmentFlag.AlignTop)
    lay.addLayout(head)
    lay.addSpacing(8)
    body = vbox(spacing=0)
    lay.addLayout(body)
    lay.addStretch(1)
    return host, body


class KeyField(QWidget):
    """Masked key input with a show/hide button and its source badge."""

    def __init__(self, spec: SecretSpec, settings) -> None:
        super().__init__()
        self.spec, self.settings = spec, settings
        lay = vbox(self, spacing=8)
        top = hbox(spacing=8)
        top.addWidget(label(spec.label.split(" · ", 1)[-1], "sub"))
        src = settings.secret_source(spec)
        self.badge = Badge({"env": "из .env", "keyring": "сохранён"}.get(src, "не задан"),
                           {"env": "active", "keyring": "success"}.get(src, "muted"))
        top.addWidget(self.badge)
        top.addStretch(1)
        lay.addLayout(top)
        row = hbox(spacing=8)
        self.edit = QLineEdit()
        self.edit.setProperty("role", "mono")
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(spec.help or spec.env)
        self.original = settings.secret(spec) if src == "keyring" else ""
        self.edit.setText(self.original)
        if src == "env":
            self.edit.setEnabled(False)
            self.edit.setPlaceholderText(f"Задан переменной {spec.env} в .env — измените его там")
        row.addWidget(self.edit, 1)
        self.show_btn = button("Показать", "eye", on_click=self._toggle)
        self.show_btn.setEnabled(src != "env")
        row.addWidget(self.show_btn)
        lay.addLayout(row)

    def _toggle(self) -> None:
        hidden = self.edit.echoMode() == QLineEdit.EchoMode.Password
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_btn.setText("Скрыть" if hidden else "Показать")
        self.show_btn.setIcon(icons.icon("eye-off" if hidden else "eye", theme.TEXT, 16))

    def changed(self) -> bool:
        return self.edit.isEnabled() and self.edit.text().strip() != self.original

    def save(self) -> None:
        self.settings.set_secret(self.spec, self.edit.text())
        self.original = self.edit.text().strip()
        src = "keyring" if self.original else ""
        self.badge.set("сохранён" if src else "не задан", "success" if src else "muted")


class SettingsPage(Page):
    title = "Настройки"
    rail_key = "settings"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, scroll=False, margins=(60, 48, 60, 40))
        self.body.addWidget(PageHeader("Параметры приложения", "Настройки"))
        self.body.addSpacing(29)
        grid = hbox(spacing=28)
        self.body.addLayout(grid, 1)

        nav = Card(padding=8, spacing=2)
        nav.setFixedWidth(230)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, QWidget] = {}
        for key, text, ic in SECTIONS:
            b = button(f"  {text}", variant="nav")
            b.setIcon(icons.icon(ic, theme.SUB, 17, "#C3BBFF"))
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.show_section(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            nav.lay.addWidget(b)
        nav.lay.addStretch(1)
        grid.addWidget(nav, 0, Qt.AlignmentFlag.AlignTop)

        content = Card()
        grid.addWidget(content, 1)
        self.stack = QStackedWidget()
        content.lay.addWidget(self.stack)
        self.sections: dict[str, QWidget] = {}
        for key, _, _ in SECTIONS:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            holder = QWidget()
            hl = vbox(holder, margins=(28, 25, 28, 25))
            area.setWidget(holder)
            self.stack.addWidget(area)
            self.sections[key] = holder
            setattr(self, f"_{key}_layout", hl)
        self.key_fields: list[KeyField] = []

    # ------------------------------------------------------------
    def on_enter(self, section: str = "tools", **kwargs) -> None:
        self.show_section(section if section in self.sections else "tools")

    def show_section(self, key: str) -> None:
        self.nav_buttons[key].setChecked(True)
        lay = getattr(self, f"_{key}_layout")
        clear_layout(lay)
        getattr(self, f"_build_{key}")(lay)
        self.stack.setCurrentIndex([k for k, _, _ in SECTIONS].index(key))

    # ------------------------------------------------------------ general
    def _build_general(self, lay) -> None:
        s = self.ctx.settings
        host, body = section("Общие", "Поведение приложения по умолчанию.")
        region = QComboBox()
        for code, text in REGIONS:
            region.addItem(text, code)
        region.setCurrentIndex(max(0, region.findData(s.get("default_region"))))
        region.currentIndexChanged.connect(lambda _i: s.set("default_region", region.currentData()))
        region.setMinimumWidth(220)
        body.addWidget(setting_row("Регион по умолчанию", "Для номеров телефона без кода страны", region))
        par = QSpinBox()
        par.setRange(1, 5)
        par.setValue(int(s.get("max_parallel_tools", 3)))
        par.valueChanged.connect(lambda v: s.set("max_parallel_tools", v))
        par.setMinimumWidth(100)
        body.addWidget(setting_row("Параллельных инструментов",
                                   "Сколько инструментов работают одновременно. Применяется после перезапуска.", par))
        mb = QSpinBox()
        mb.setRange(1, 2048)
        mb.setSuffix(" МБ")
        mb.setValue(int(s.get("max_file_mb", 100)))
        mb.valueChanged.connect(lambda v: s.set("max_file_mb", v))
        mb.setMinimumWidth(100)
        body.addWidget(setting_row("Максимальный размер файла", "Для анализа метаданных ExifTool", mb))
        body.addWidget(setting_row("Экран с условиями использования",
                                   "Показать приветствие и дисклеймер снова",
                                   button("Показать", on_click=self._reset_disclaimer), last=True))
        lay.addWidget(host)

    def _reset_disclaimer(self) -> None:
        self.ctx.settings.set("disclaimer_accepted", False)
        self.ctx.go("welcome")

    # ------------------------------------------------------------ tools
    def _build_tools(self, lay) -> None:
        adapters = self.ctx.adapters()
        installed = sum(1 for a in adapters.values() if a.availability()[0])
        host, body = section("Инструменты", "Управление локальными модулями анализа.",
                             Badge(f"{installed} из {len(adapters)} установлено",
                                   "success" if installed == len(adapters) else "warn"))
        items = list(adapters.items())
        for i, (name, a) in enumerate(items):
            ok, reason = a.availability()
            w = QWidget()
            w.setMinimumHeight(86)
            row = hbox(w, spacing=16)
            row.addWidget(ToolIcon(a.icon, a.accent))
            col = vbox(spacing=5)
            col.addStretch(1)
            t = QLabel(f"{a.title} <span style='color:{theme.SUB}; font-size:12px;'>· v{a.version() or '?'}</span>")
            t.setTextFormat(Qt.TextFormat.RichText)
            col.addWidget(t)
            col.addWidget(label(a.description if ok else reason, "sub" if ok else "error", wrap=True))
            col.addStretch(1)
            row.addLayout(col, 1)
            row.addWidget(Badge("Установлен" if ok else "Не найден", "success" if ok else "error"))
            tg = Toggle(self.ctx.settings.tool_enabled(name))
            tg.setToolTip("Включить / отключить инструмент")
            tg.toggled.connect(lambda on, n=name: self.ctx.settings.set_tool_option(n, "enabled", on))
            row.addWidget(tg)
            row.addWidget(button("Параметры", size="sm", on_click=lambda ad=a: self._tool_options(ad)))
            body.addWidget(w)
            if i < len(items) - 1:
                body.addWidget(rule())
        body.addSpacing(19)
        body.addWidget(label(f"Встроенные инструменты лежат в {tools_dir()}. Обновление: "
                             "python scripts\\fetch_tools.py --force (см. README).", "sub", wrap=True))
        lay.addWidget(host)

    def _tool_options(self, adapter) -> None:
        dlg = ToolOptionsDialog(self, adapter, self.ctx.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.ctx.toast(f"Параметры {adapter.title} сохранены")

    # ------------------------------------------------------------ keys
    def _build_keys(self, lay) -> None:
        host, body = section("API-ключи", "Ключи хранятся в Диспетчере учётных данных Windows. Значение скрыто "
                                          "до нажатия кнопки показа. Переменные из .env имеют приоритет.")
        self.key_fields = []
        for a in self.ctx.adapters().values():
            if not a.secrets:
                continue
            body.addSpacing(18)
            t = label(a.title)
            t.setStyleSheet("font-weight:600;")
            body.addWidget(t)
            for spec in a.secrets:
                body.addSpacing(14)
                f = KeyField(spec, self.ctx.settings)
                self.key_fields.append(f)
                body.addWidget(f)
        note = QFrame()
        note.setProperty("keynote", True)
        nl = vbox(note, margins=(14, 14, 14, 14))
        nl.addWidget(label("Добавляйте только ключи от сервисов, к которым у вас есть легальный доступ. "
                           "Ключи не попадают в отчёты, логи и настройки приложения.", "sub", wrap=True))
        body.addSpacing(22)
        body.addWidget(note)
        body.addSpacing(28)
        row = hbox()
        row.addWidget(button("Сохранить изменения", variant="primary", on_click=self._save_keys))
        row.addStretch(1)
        body.addLayout(row)
        lay.addWidget(host)

    def _save_keys(self) -> None:
        changed = [f for f in self.key_fields if f.changed()]
        try:
            for f in changed:
                f.save()
        except Exception as exc:
            self.ctx.toast(f"Не удалось сохранить ключи: {exc}", "error")
            return
        self.ctx.toast("Ключи сохранены" if changed else "Изменений нет")

    # ------------------------------------------------------------ storage
    def _build_storage(self, lay) -> None:
        host, body = section("Хранилище", "Где приложение хранит историю, настройки и отчёты.")
        db = self.ctx.storage.path
        size = db.stat().st_size if db.exists() else 0
        scans = len(self.ctx.storage.list_scans(limit=100000))
        ddir = data_dir()
        body.addWidget(setting_row("Папка данных", str(ddir),
                                   button("Открыть", "folder-open", size="sm",
                                          on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ddir))))))
        body.addWidget(setting_row("История сканов", f"{fmt.plural(scans, 'скан', 'скана', 'сканов')} · база {fmt.size(size)}",
                                   button("Очистить историю", "trash", variant="danger", size="sm",
                                          on_click=self._clear_history)))
        rd = reports_dir()
        body.addWidget(setting_row("Папка отчётов", str(rd),
                                   button("Открыть", "folder-open", size="sm",
                                          on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(rd)))),
                                   last=True))
        lay.addWidget(host)

    def _clear_history(self) -> None:
        if self.ctx.engine.active_scans():
            self.ctx.toast("Дождитесь завершения активных сканов", "error")
            return
        if confirm(self, "Очистить историю?", "Все сканы и находки будут удалены без возможности восстановления. "
                                             "Файлы экспортированных отчётов останутся на диске.",
                   "Очистить", danger=True):
            for s in self.ctx.storage.list_scans(limit=100000):
                self.ctx.storage.delete_scan(s.id)
            self.ctx.toast("История очищена")
            self.show_section("storage")

    # ------------------------------------------------------------ about
    def _build_about(self, lay) -> None:
        host, body = section(f"{APP_TITLE} {APP_VERSION}",
                             "Локальное приложение для проверки собственного цифрового следа и разрешённых "
                             "исследований. Все данные остаются на этом компьютере.")
        notices = app_dir() / "THIRD_PARTY_NOTICES.md"
        links = hbox(spacing=8)
        links.addWidget(button("Исходный код", "arrow-up-right", size="sm",
                               on_click=lambda: QDesktopServices.openUrl(QUrl(APP_REPO))))
        links.addWidget(button("Сторонние лицензии", "file-text", size="sm",
                               on_click=lambda: QDesktopServices.openUrl(
                                   QUrl.fromLocalFile(str(notices)) if notices.exists()
                                   else QUrl(f"{APP_REPO}/blob/main/THIRD_PARTY_NOTICES.md"))))
        links.addStretch(1)
        body.addSpacing(12)
        body.addWidget(label(f"Лицензия OSINT Hub: GNU {APP_LICENSE}. Исходный код: {APP_REPO}", "sub", wrap=True))
        body.addSpacing(8)
        body.addLayout(links)
        body.addSpacing(10)
        for i, (name, a) in enumerate(self.ctx.adapters().items()):
            link = button("Сайт проекта", "arrow-up-right", variant="text", size="sm",
                          on_click=lambda u=a.homepage: QDesktopServices.openUrl(QUrl(u)))
            body.addWidget(setting_row(f"{a.title} · v{a.version() or '?'}",
                                       f"{a.description} · лицензия {LICENSES.get(name, '—')}", link,
                                       last=i == len(self.ctx.adapters()) - 1))
        body.addSpacing(16)
        body.addWidget(label("Интерфейс: шрифты Inter и JetBrains Mono (OFL), иконки Lucide (ISC), карта Leaflet "
                             "(BSD-2) и тайлы © участники OpenStreetMap.", "sub", wrap=True))
        body.addSpacing(16)
        notice = QFrame()
        notice.setProperty("notice", True)
        nl = hbox(notice, margins=(16, 16, 16, 16), spacing=12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("shield-alert", theme.WARNING, 18))
        nl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        nl.addWidget(label("Используйте приложение только для проверки собственного цифрового следа и исследований, "
                           "на которые у вас есть разрешение. Соблюдайте законодательство о персональных данных.",
                           "noticetext", wrap=True), 1)
        body.addWidget(notice)
        lay.addWidget(host)
