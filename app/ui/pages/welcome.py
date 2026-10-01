"""Mockup 01: first-run disclaimer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel

from ...config import APP_TITLE
from .. import icons, theme
from ..widgets import Card, CheckBox, button, hbox, label
from .base import Page


class WelcomePage(Page):
    title = "Первый запуск"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, margins=(24, 24, 24, 48))
        self.body.addStretch(1)
        card = Card(padding=40)
        card.setFixedWidth(520)
        logo = QLabel()
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(icons.pixmap("brand", "#AB9FFF", 29))
        logo.setStyleSheet("background:#282344; border-radius:16px;")
        card.lay.addWidget(logo)
        card.lay.addSpacing(24)
        title = label(APP_TITLE, "h1")
        card.lay.addWidget(title)
        card.lay.addSpacing(8)
        card.lay.addWidget(label("Один рабочий стол для анализа открытых данных и собственного цифрового следа.",
                                 "lead", wrap=True))
        card.lay.addSpacing(30)

        notice = QFrame()
        notice.setProperty("notice", True)
        nl = hbox(notice, margins=(16, 16, 16, 16), spacing=12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("shield-alert", theme.WARNING, 18))
        ic.setFixedSize(18, 22)
        nl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        nl.addWidget(label(
            "Используйте приложение для проверки собственного цифрового следа и исследований, на которые у вас "
            "есть разрешение. Соблюдайте законодательство о персональных данных (в том числе 152-ФЗ и GDPR) "
            "и правила сервисов.", "noticetext", wrap=True), 1)
        card.lay.addWidget(notice)
        card.lay.addSpacing(24)

        self.agree = CheckBox("Понимаю и согласен")
        card.lay.addWidget(self.agree)
        card.lay.addSpacing(28)
        bottom = hbox()
        bottom.addWidget(label("Локальное рабочее пространство", "sub"))
        bottom.addStretch(1)
        self.start = button("Начать", "arrow-right", variant="primary", icon_right=True, on_click=self._accept)
        self.start.setEnabled(False)
        bottom.addWidget(self.start)
        card.lay.addLayout(bottom)
        self.agree.toggled.connect(self.start.setEnabled)

        row = hbox()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addStretch(1)

    def _accept(self) -> None:
        if not self.agree.isChecked():
            return
        self.ctx.settings.set("disclaimer_accepted", True)
        self.ctx.go("home")

    def on_enter(self, **kwargs) -> None:
        self.agree.setChecked(False)
