"""Base class for full-window pages."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ..context import AppContext
from ..widgets import hbox, vbox


class Page(QWidget):
    """A page inside the main stack.

    ``self.body`` is the content layout. With ``scroll=True`` the content is
    placed in a scroll area; ``max_width`` centres it like the mockups.
    """

    title = ""          # shown in the window title
    rail_key = "home"   # which rail item is highlighted

    def __init__(self, ctx: AppContext, *, scroll: bool = True, margins: tuple[int, int, int, int] = (60, 48, 60, 40),
                 max_width: int | None = None, spacing: int = 0) -> None:
        super().__init__()
        self.ctx = ctx
        self.setProperty("page", True)
        outer = vbox(self)
        content = QWidget()
        content.setProperty("page", True)
        self.content = content
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setWidget(content)
            outer.addWidget(area)
            self.scroll_area: QScrollArea | None = area
        else:
            outer.addWidget(content)
            self.scroll_area = None
        wrap = vbox(content, margins=margins)
        inner = QWidget()
        self.body: QVBoxLayout = vbox(inner, spacing=spacing)
        if max_width:
            # Centre a column that grows up to max_width (side stretches take the rest).
            inner.setMaximumWidth(max_width)
            row = hbox()
            row.addStretch(1)
            row.addWidget(inner, 100)
            row.addStretch(1)
            wrap.addLayout(row)
            wrap.addStretch(1)
        else:
            wrap.addWidget(inner, 1)

    def on_enter(self, **kwargs: Any) -> None:
        """Called every time the page becomes visible."""

    def on_leave(self) -> None:
        """Called when another page is shown."""

    def scroll_top(self) -> None:
        if self.scroll_area is not None:
            self.scroll_area.verticalScrollBar().setValue(0)
