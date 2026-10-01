"""Mockup 08: Sherlock profile cards."""

from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox

from ...core.storage import ScanRecord
from .. import fmt
from ..dialogs import open_export
from ..widgets import (Badge, Card, ElidedLabel, PageHeader, ResponsiveGrid, Segmented, SiteLogo, button, hbox,
                       label, vbox)
from .base import Page

PAGE_SIZE = 60
STATUS_BADGE = {"Claimed": ("Найден", "success"), "Available": ("Не найден", "muted"),
                "Unknown": ("Ошибка", "warn"), "WAF": ("Блокировка", "warn"), "Illegal": ("Недопустим", "muted")}


class ProfileCard(Card):
    def __init__(self, site: dict, confidence: str | None) -> None:
        super().__init__(padding=(19, 18, 19, 18), spacing=0)
        self.setMinimumHeight(143)
        top = hbox(spacing=12)
        top.addWidget(SiteLogo(site["site"]))
        col = vbox(spacing=3)
        name = label(site["site"])
        name.setStyleSheet("font-weight:600;")
        col.addWidget(name)
        if confidence:
            col.addWidget(label(f"{fmt.CONFIDENCE[confidence]} достоверность", "sub"))
        elif site.get("context"):
            col.addWidget(ElidedLabel(site["context"], "sub"))
        else:
            col.addWidget(label("Профиль не найден" if site.get("status") == "Available" else "Нет данных", "sub"))
        top.addLayout(col, 1)
        text, variant = STATUS_BADGE.get(site.get("status", ""), (site.get("status", ""), "neutral"))
        top.addWidget(Badge(text, variant), 0, Qt.AlignmentFlag.AlignTop)
        self.lay.addLayout(top)
        self.lay.addStretch(1)
        bottom = hbox(spacing=8)
        url = site.get("url_user", "")
        parsed = urlparse(url)
        handle = (parsed.netloc + parsed.path).rstrip("/") if url else ""
        bottom.addWidget(ElidedLabel(handle, "sub"), 1)
        if url.startswith(("https://", "http://")):
            open_btn = button("Открыть ↗", size="sm",
                              on_click=lambda u=url: QDesktopServices.openUrl(QUrl(u)))
            open_btn.setToolTip(url)
            bottom.addWidget(open_btn)
        self.lay.addLayout(bottom)


class SherlockPage(Page):
    title = "Sherlock"
    rail_key = "home"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, margins=(60, 48, 60, 40))
        self.scan: ScanRecord | None = None
        self.sites: list[dict] = []
        self.conf: dict[str, str] = {}
        self.shown = 0

        self.header = PageHeader("Результат инструмента", "Профили", "")
        self.header.actions.addWidget(button("К результатам", "arrow-left", on_click=self._back))
        self.header.actions.addWidget(button("Экспорт", "download", variant="primary", on_click=self._export))
        self.body.addWidget(self.header)
        self.body.addSpacing(27)

        controls = hbox()
        self.seg = Segmented(["Только найденные", "Все проверенные"])
        self.seg.changed.connect(lambda _i: self._render())
        controls.addWidget(self.seg)
        controls.addStretch(1)
        self.sort = QComboBox()
        self.sort.addItem("Сортировка: достоверность", "confidence")
        self.sort.addItem("Сортировка: название", "name")
        self.sort.setMinimumWidth(230)
        self.sort.currentIndexChanged.connect(lambda _i: self._render())
        controls.addWidget(self.sort)
        self.body.addLayout(controls)
        self.body.addSpacing(19)

        self.grid = ResponsiveGrid(min_col=280, max_cols=3, spacing=13)
        self.body.addWidget(self.grid)
        self.more_btn = button("Показать ещё", on_click=self._more)
        self.body.addSpacing(14)
        row = hbox()
        row.addStretch(1)
        row.addWidget(self.more_btn)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addSpacing(18)
        self.body.addWidget(label("Совпадение никнейма само по себе не подтверждает принадлежность профиля "
                                  "конкретному человеку.", "sub", wrap=True))
        self.body.addStretch(1)

    def on_enter(self, scan_id: int | None = None, **kwargs) -> None:
        if scan_id is None:
            return
        scan = self.ctx.storage.get_scan(scan_id)
        res = scan.results.get("sherlock") if scan else None
        if scan is None or res is None or not isinstance(res.raw, dict):
            self.ctx.go("results", scan_id=scan_id)
            return
        self.scan = scan
        raw = res.raw
        self.sites = list(raw.get("sites", []))
        self.conf = {f.extra.get("site", f.source): f.confidence for f in res.findings}
        found = sum(1 for s in self.sites if s.get("status") == "Claimed")
        total = raw.get("total") or len(self.sites)
        self.header.title.setText(f"Профили @{raw.get('username', scan.target)}")
        verb = "нашёл" if res.status == "done" else "успел найти"
        self.header.set_lead(f"Sherlock проверил {total} сайтов и {verb} "
                             f"{fmt.plural(found, 'возможное совпадение', 'возможных совпадения', 'возможных совпадений')}.")
        self.seg.set_label(0, f"Только найденные  {found}")
        self.seg.set_label(1, f"Все проверенные  {len(self.sites)}")
        self.seg.set_current(0)
        self._render()
        self.scroll_top()

    def _ordered(self) -> list[dict]:
        sites = self.sites if self.seg.current() == 1 else [s for s in self.sites if s.get("status") == "Claimed"]
        if self.sort.currentData() == "name":
            return sorted(sites, key=lambda s: s["site"].lower())
        rank = {"high": 0, "medium": 1, "low": 2}
        return sorted(sites, key=lambda s: (s.get("status") != "Claimed", rank.get(self.conf.get(s["site"], ""), 3),
                                            s["site"].lower()))

    def _render(self) -> None:
        self.shown = 0
        self.grid.set_items([])
        self._more()

    def _more(self) -> None:
        ordered = self._ordered()
        nxt = ordered[self.shown:self.shown + PAGE_SIZE]
        cards = [ProfileCard(s, self.conf.get(s["site"]) if s.get("status") == "Claimed" else None) for s in nxt]
        if self.shown == 0:
            self.grid.set_items(cards)
        else:
            self.grid.append_items(cards)
        self.shown += len(nxt)
        self.more_btn.setVisible(self.shown < len(ordered))
        if not ordered:
            empty = Card(padding=24)
            empty.lay.addWidget(label("Sherlock не нашёл профилей с этим никнеймом.", "sub"))
            self.grid.set_items([empty])

    def _back(self) -> None:
        if self.scan:
            self.ctx.go("results", scan_id=self.scan.id)

    def _export(self) -> None:
        if self.scan:
            open_export(self, self.ctx, self.scan.id)
