"""Mockups 02–03: home screen with type detection and tool selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QFrame, QGraphicsOpacityEffect, QLineEdit, QWidget

from ...core.detect import Detection, detect
from ...core.schema import TargetType
from .. import fmt, icons, theme
from ..widgets import (Badge, Card, PageHeader, ResponsiveGrid, SectionHeader, Toggle, ToolIcon, button,
                       clear_layout, hbox, icon_label, label)
from .base import Page

HINT_FOR_TYPE = {
    TargetType.FILE: "Доступен при загрузке файла",
    TargetType.PHONE: "Доступен для номера телефона",
    TargetType.EMAIL: "Доступен для email",
    TargetType.USERNAME: "Доступен для никнейма",
    TargetType.DOMAIN: "Доступен для домена",
}


class ToolTile(Card):
    """Tool card: idle (status badge) or selection mode (toggle)."""

    def __init__(self, ctx, name: str) -> None:
        super().__init__(hoverable=True, padding=16, spacing=8)
        self.ctx, self.name = ctx, name
        a = ctx.adapter(name)
        self.adapter = a
        self.setMinimumHeight(164)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        top = hbox()
        top.addWidget(ToolIcon(a.icon, a.accent))
        top.addStretch(1)
        self.badge = Badge("Готов", "success")
        self.toggle = Toggle()
        self.toggle.toggled.connect(self._on_toggle)
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        self.lay.addLayout(top)
        self.lay.addSpacing(9)
        self.lay.addWidget(label(a.title, "tiletitle"))
        self.desc = label(a.description, "sub", wrap=True)
        self.lay.addWidget(self.desc)
        self.lay.addStretch(1)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(1.0)
        self.setGraphicsEffect(self._fx)
        self.selectable = False
        self.on_change = lambda: None

    def set_idle(self) -> None:
        self.selectable = False
        self.toggle.hide()
        self.badge.show()
        ok, reason = self.adapter.availability()
        if not self.ctx.settings.tool_enabled(self.name):
            self.badge.set("Отключён", "muted")
        elif not ok:
            self.badge.set("Не установлен", "error")
            self.badge.setToolTip(reason)
        else:
            self.badge.set("Готов", "success")
        self.desc.setText(self.adapter.description)
        self._fx.setOpacity(1.0)
        theme.set_prop(self, "state", None)

    def set_selectable(self, applicable: bool, ready: bool, selected: bool, hint: str) -> None:
        self.selectable = applicable and ready
        self.badge.setVisible(applicable and not ready)
        if applicable and not ready:
            self.badge.set("Не установлен" if self.ctx.settings.tool_enabled(self.name) else "Отключён",
                           "error" if self.ctx.settings.tool_enabled(self.name) else "muted")
        self.toggle.setVisible(self.selectable or not applicable)
        self.toggle.setEnabled(self.selectable)
        self.toggle.blockSignals(True)
        self.toggle.setChecked(selected and self.selectable)
        self.toggle._set_knob(1.0 if selected and self.selectable else 0.0)
        self.toggle.blockSignals(False)
        self.desc.setText(self.adapter.description if applicable else hint)
        self._fx.setOpacity(1.0 if applicable else 0.43)
        theme.set_prop(self, "state", "selected" if selected and self.selectable else None)

    def _on_toggle(self, on: bool) -> None:
        theme.set_prop(self, "state", "selected" if on else None)
        self.on_change()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            if self.selectable:
                self.toggle.toggle()
            elif TargetType.FILE in self.adapter.input_types and self.badge.text() == "Готов":
                self.ctx.window.pages["home"].choose_file()
        super().mouseReleaseEvent(e)


class RecentRow(QFrame):
    def __init__(self, ctx, scan, last: bool) -> None:
        super().__init__()
        self.ctx, self.scan_id = ctx, scan.id
        self.setProperty("tablerow", True)
        self.setProperty("clickable", True)
        if last:
            self.setProperty("last", True)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = hbox(self, margins=(17, 0, 17, 0), spacing=13)
        row.addWidget(icon_label(icons.TYPE_ICON.get(scan.target_type, "search"), theme.SUB, 16))
        value = label(fmt.target_display(scan.target, scan.target_type))
        value.setStyleSheet("font-weight:500;")
        row.addWidget(value, 4)
        if ctx.engine.is_active(scan.id):
            badge = Badge("Идёт", "active")
        elif scan.status == "error":
            badge = Badge("Ошибка", "error")
        else:
            badge = Badge(fmt.findings(scan.findings_count), "success" if scan.findings_count else "muted")
        row.addWidget(badge)
        row.addStretch(5)
        row.addWidget(label(fmt.relative(scan.created_at), "sub"))
        row.addWidget(icon_label("chevron-right", theme.SUB, 16))

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.ctx.open_scan(self.scan_id)


class HomePage(Page):
    title = "Главная"
    rail_key = "home"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, margins=(60, 48, 60, 40), max_width=1160)
        self.detection: Detection | None = None
        self.forced_type: TargetType | None = None

        self.body.addWidget(PageHeader("Рабочее пространство", "Главная"))

        # ---- hero
        self.body.addSpacing(64)
        self.hero_title = label("Что будем проверять?", "hero")
        self.hero_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_sub = label("Введите цель — мы определим тип и предложим подходящие инструменты.", "lead")
        self.hero_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.hero_title)
        self.body.addSpacing(10)
        self.body.addWidget(self.hero_sub)
        self.body.addSpacing(28)

        self.searchbox = QFrame()
        self.searchbox.setProperty("searchbox", True)
        self.searchbox.setFixedHeight(64)
        self.searchbox.setMaximumWidth(838)
        sb = hbox(self.searchbox, margins=(18, 7, 8, 7), spacing=14)
        self.type_icon = icon_label("search", theme.SUB, 20)
        sb.addWidget(self.type_icon)
        self.input = QLineEdit()
        self.input.setProperty("role", "search")
        self.input.setPlaceholderText("Email, телефон, никнейм, домен или перетащи файл")
        self.input.setClearButtonEnabled(True)
        self.input.setAccessibleName("Цель скана")
        sb.addWidget(self.input, 1)
        sb.addWidget(button("", "paperclip", variant="icon", tooltip="Выбрать файл для ExifTool",
                            on_click=self.choose_file))
        self.scan_btn = button("Сканировать", variant="primary", size="lg", on_click=self.submit)
        self.scan_btn.setMinimumWidth(140)
        sb.addWidget(self.scan_btn)
        row = hbox()
        row.addStretch(1)
        row.addWidget(self.searchbox, 100)
        row.addStretch(1)
        self.body.addLayout(row)
        self.input.installEventFilter(self)

        self.body.addSpacing(13)
        self.example = label("Например: name@example.org · +7 900 000-00-00 · @nickname · example.com", "disabled")
        self.example.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.example)
        self.detected = QWidget()
        dl = hbox(self.detected, spacing=7)
        dl.addStretch(1)
        self.detected_icon = icon_label("circle-check", "#BCB4FF", 15)
        dl.addWidget(self.detected_icon)
        self.detected_text = label("", "accent")
        dl.addWidget(self.detected_text)
        self.alt_box = hbox(spacing=6)
        dl.addLayout(self.alt_box)
        dl.addStretch(1)
        self.detected.hide()
        self.body.addWidget(self.detected)
        self.body.addSpacing(52)

        # ---- tools
        self.tools_count = label("", "sub")
        self.tools_header = SectionHeader("Инструменты", self.tools_count)
        self.body.addWidget(self.tools_header)
        self.body.addSpacing(16)
        self.grid = ResponsiveGrid(min_col=150, max_cols=5, spacing=12)
        self.tiles: dict[str, ToolTile] = {}
        tiles = []
        for name in ctx.adapters():
            t = ToolTile(ctx, name)
            t.on_change = self._update_selection_count
            self.tiles[name] = t
            tiles.append(t)
        self.grid.set_items(tiles)
        self.body.addWidget(self.grid)

        # ---- recent
        self.body.addSpacing(30)
        all_btn = button("Вся история", "arrow-right", variant="text", size="sm", icon_right=True,
                         on_click=lambda: ctx.go("history"))
        self.body.addWidget(SectionHeader("Последние сканы", all_btn))
        self.body.addSpacing(12)
        self.recent = Card()
        self.body.addWidget(self.recent)
        self.recent_empty = label("Здесь появятся последние сканы.", "sub")
        self.recent_empty.setContentsMargins(17, 14, 17, 14)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self._detect)
        self.input.textChanged.connect(self._on_text)
        self.input.returnPressed.connect(self.submit)
        self.error = label("", "error")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ctx.bridge.history_changed.connect(self._refresh_recent_if_visible)

    # ------------------------------------------------------------ events
    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if obj is self.input and e.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            theme.set_prop(self.searchbox, "focused", e.type() == QEvent.Type.FocusIn)
        return super().eventFilter(obj, e)

    def on_enter(self, **kwargs) -> None:
        if "prefill" in kwargs:
            self.input.setText(kwargs["prefill"])
        self._refresh_recent()
        self._detect()
        self.input.setFocus()

    def _refresh_recent_if_visible(self) -> None:
        if self.isVisible():
            self._refresh_recent()

    def _refresh_recent(self) -> None:
        clear_layout(self.recent.lay)
        scans = self.ctx.storage.list_scans(limit=5)
        if not scans:
            self.recent.lay.addWidget(label("Здесь появятся последние сканы.", "sub"))
            self.recent.lay.setContentsMargins(17, 14, 17, 14)
            return
        self.recent.lay.setContentsMargins(0, 0, 0, 0)
        for i, s in enumerate(scans):
            self.recent.lay.addWidget(RecentRow(self.ctx, s, i == len(scans) - 1))

    # ------------------------------------------------------------ detection
    def _on_text(self, _text: str) -> None:
        self.forced_type = None
        self._debounce.start()

    def _detect(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.detection = None
        else:
            self.detection = detect(text, self.ctx.settings.get("default_region"))
            if self.forced_type and self.forced_type in [self.detection.type, *self.detection.alternatives]:
                from ...core import validation

                try:
                    value = validation.normalize(text, self.forced_type,
                                                 default_region=self.ctx.settings.get("default_region"))
                    alts = [t for t in [self.detection.type, *self.detection.alternatives] if t != self.forced_type]
                    self.detection = Detection(self.forced_type, value, alts)
                except validation.ValidationError:
                    pass
        self._render_detection()

    def _render_detection(self) -> None:
        d = self.detection
        recognized = d is not None and d.type is not None
        self.hero_title.setText("Подготовка скана" if recognized else "Что будем проверять?")
        self.hero_sub.setText("Тип цели определён. Проверьте выбор инструментов перед запуском." if recognized
                              else "Введите цель — мы определим тип и предложим подходящие инструменты.")
        self.example.setVisible(d is None)
        self.detected.setVisible(d is not None)
        clear_layout(self.alt_box)
        if d is not None and d.type is None:
            self.detected_icon.setPixmap(icons.pixmap("circle-alert", theme.ERROR_SOFT, 15))
            self.detected_text.setProperty("role", "error")
            self.detected_text.setText(d.error or "Не удалось определить тип")
            theme.polish(self.detected_text)
        elif recognized:
            self.detected_icon.setPixmap(icons.pixmap("circle-check", "#BCB4FF", 15))
            self.detected_text.setProperty("role", "accent")
            self.detected_text.setText(f"Распознано: {d.type.label.lower()}")
            theme.polish(self.detected_text)
            for alt in d.alternatives[:3]:
                chip = button(f"или {alt.label.lower()}", variant="chip",
                              on_click=lambda t=alt: self._force(t))
                self.alt_box.addWidget(chip)
            self.type_icon.setPixmap(icons.pixmap(icons.TYPE_ICON.get(d.type.value, "search"), theme.ACCENT_SOFT, 20))
        if not recognized:
            self.type_icon.setPixmap(icons.pixmap("search", theme.SUB, 20))
        self._render_tiles()

    def _force(self, ttype: TargetType) -> None:
        self.forced_type = ttype
        self._detect()

    def _render_tiles(self) -> None:
        d = self.detection
        if d is None or d.type is None:
            self.tools_header.title.setText("Инструменты")
            ready = 0
            for t in self.tiles.values():
                t.set_idle()
                ready += t.badge.text() == "Готов"
            self.tools_count.setText(f"{ready} из {len(self.tiles)} готовы к работе")
            return
        self.tools_header.title.setText("Выбор инструментов")
        for name, t in self.tiles.items():
            applicable = d.type in t.adapter.input_types
            ready = self.ctx.tool_ready(name)
            hint = next((HINT_FOR_TYPE[tt] for tt in HINT_FOR_TYPE if tt in t.adapter.input_types),
                        t.adapter.description)
            t.set_selectable(applicable, ready, selected=applicable and ready, hint=hint)
        self._update_selection_count()

    def _update_selection_count(self) -> None:
        if self.detection is None or self.detection.type is None:
            return
        chosen = self.selected_tools()
        self.tools_count.setText(f"Выбрано {len(chosen)} из {len(self.tiles)}")
        self.scan_btn.setEnabled(bool(chosen))

    def selected_tools(self) -> list[str]:
        return [n for n, t in self.tiles.items() if t.selectable and t.toggle.isChecked()]

    # ------------------------------------------------------------ actions
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Файл для анализа метаданных", str(Path.home()),
                                              "Изображения и документы (*.jpg *.jpeg *.png *.heic *.tif *.tiff *.gif "
                                              "*.webp *.pdf *.docx *.xlsx *.pptx *.doc *.mp4 *.mov);;Все файлы (*)")
        if path:
            self.ctx.window.start_file_scan(path)

    def submit(self) -> None:
        self._debounce.stop()
        self._detect()
        d = self.detection
        if d is None:
            self.input.setFocus()
            return
        if d.type is None:
            self.ctx.toast(d.error or "Не удалось определить тип цели", "error")
            return
        tools = self.selected_tools()
        if not tools:
            self.ctx.toast("Выберите хотя бы один инструмент", "error")
            return
        if self.ctx.start_scan(d.value, d.type, tools) is not None:
            self.input.clear()
