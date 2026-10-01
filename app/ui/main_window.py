"""Main window: navigation rail, page stack, drag-and-drop overlay and toasts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QCloseEvent, QColor, QDragEnterEvent, QDropEvent, QPainter, QShowEvent
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QLabel, QMainWindow, QStackedWidget,
                               QWidget)

from ..config import APP_TITLE
from . import icons, theme
from .context import AppContext
from .pages.base import Page
from .widgets import Toast, hbox, label, vbox

log = logging.getLogger(__name__)


class RailButton(QAbstractButton):
    """40×40 icon button with the active indicator bar from the mockups."""

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon_name
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCheckable(True)
        self.setFixedSize(QSize(52, 40))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(6, 0, 40, 40)
        color = theme.SUB
        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.RAIL_ACTIVE_BG))
            p.drawRoundedRect(box, 9, 9)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(0, 8, 2, 24), 1, 1)
            color = theme.RAIL_ACTIVE_FG
        elif self._hover and self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.HOVER))
            p.drawRoundedRect(box, 9, 9)
            color = theme.TEXT
        if not self.isEnabled():
            color = theme.DISABLED
        p.drawPixmap(int(box.x()) + 11, 11, icons.pixmap(self._icon, color, 19))


class Rail(QFrame):
    """Left navigation rail (64 px)."""

    ITEMS = [("home", "home", "Главная"), ("history", "history", "История"),
             ("reports", "file-text", "Отчёты"), ("settings", "settings", "Настройки")]

    def __init__(self, on_nav, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(64)
        self.setStyleSheet(f"Rail {{ background:{theme.BG}; border-right:1px solid {theme.BORDER}; }}")
        lay = vbox(self, margins=(6, 22, 6, 20), spacing=14)
        brand = QLabel()
        brand.setFixedSize(36, 36)
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setPixmap(icons.pixmap("brand", "#A69AFC", 22))
        brand.setStyleSheet("background:#211D38; border-radius:10px;")
        brand.setToolTip(APP_TITLE)
        lay.addWidget(brand, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(18)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, RailButton] = {}
        for key, icon_name, tip in self.ITEMS:
            b = RailButton(icon_name, tip)
            b.clicked.connect(lambda _=False, k=key: on_nav(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.help = RailButton("help", "О программе и справка")
        self.help.setCheckable(False)
        self.help.clicked.connect(lambda: on_nav("settings", section="about"))
        lay.addWidget(self.help, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_active(self, key: str | None) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)
        else:
            self.group.setExclusive(False)
            for b in self.buttons.values():
                b.setChecked(False)
            self.group.setExclusive(True)

    def set_locked(self, locked: bool) -> None:
        for b in [*self.buttons.values(), self.help]:
            b.setEnabled(not locked)


class DropOverlay(QWidget):
    """Full-window dim layer with the dashed drop zone (mockup 04)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        outer = vbox(self)
        outer.addStretch(1)
        row = hbox()
        row.addStretch(1)
        zone = QFrame()
        zone.setProperty("dropzone", True)
        zone.setFixedSize(690, 340)
        zl = vbox(zone, spacing=8)
        zl.addStretch(1)
        ic = QLabel()
        ic.setFixedSize(64, 64)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(icons.pixmap("file-up", "#B4A9FF", 29))
        ic.setStyleSheet("background:#2A2548; border-radius:18px;")
        zl.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        zl.addSpacing(14)
        self.title = label("Отпусти файл для анализа метаданных")
        self.title.setStyleSheet("font-size:22px; font-weight:600;")
        zl.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        self.sub = label("Изображения, PDF и документы · до 100 МБ", "lead")
        zl.addWidget(self.sub, 0, Qt.AlignmentFlag.AlignHCenter)
        zl.addStretch(1)
        row.addWidget(zone)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.hide()

    def paintEvent(self, _e) -> None:
        QPainter(self).fillRect(self.rect(), QColor(8, 10, 13, 201))

    def set_message(self, title: str, sub: str) -> None:
        self.title.setText(title)
        self.sub.setText(sub)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.window = self
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1024, 680)
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = hbox(root)
        self.rail = Rail(self.navigate)
        lay.addWidget(self.rail)
        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStack")
        lay.addWidget(self.stack, 1)

        self.pages: dict[str, Page] = {}
        self._current: str | None = None
        self._build_pages()

        self.overlay = DropOverlay(root)
        self.toast = Toast(root)
        self._dark_applied = False

        if ctx.settings.get("disclaimer_accepted"):
            self.navigate("home")
        else:
            self.navigate("welcome")

    def _build_pages(self) -> None:
        from .pages.exif import ExifPage
        from .pages.history import HistoryPage
        from .pages.home import HomePage
        from .pages.reports import ReportsPage
        from .pages.results import ResultsPage
        from .pages.scan import ScanPage
        from .pages.settings import SettingsPage
        from .pages.sherlock import SherlockPage
        from .pages.welcome import WelcomePage

        for key, cls in [("welcome", WelcomePage), ("home", HomePage), ("scan", ScanPage),
                         ("results", ResultsPage), ("exif", ExifPage), ("sherlock", SherlockPage),
                         ("history", HistoryPage), ("reports", ReportsPage), ("settings", SettingsPage)]:
            page = cls(self.ctx)
            self.pages[key] = page
            self.stack.addWidget(page)

    # ------------------------------------------------------------ navigation
    def navigate(self, key: str, **kwargs: Any) -> None:
        if key != "welcome" and not self.ctx.settings.get("disclaimer_accepted"):
            key = "welcome"
        page = self.pages[key]
        if self._current and self._current != key:
            self.pages[self._current].on_leave()
        self._current = key
        self.stack.setCurrentWidget(page)
        page.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        page.setFocus()  # no stray focus ring on the first button
        self.rail.set_locked(key == "welcome")
        self.rail.set_active(None if key == "welcome" else page.rail_key)
        try:
            page.on_enter(**kwargs)
        except Exception:
            log.exception("page %s failed to open", key)
            self.toast.show_message("Не удалось открыть страницу — подробности в журнале", "error")
        self.setWindowTitle(f"{APP_TITLE} — {page.title}" if page.title else APP_TITLE)

    def current_page(self) -> str | None:
        return self._current

    # ------------------------------------------------------------ window events
    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        if not self._dark_applied:
            theme.dark_title_bar(self)
            self._dark_applied = True
            # Windows may override a size set before show(); fit 1440x900 into the screen.
            screen = self.screen().availableGeometry()
            w, h = min(1440, int(screen.width() * 0.92)), min(900, int(screen.height() * 0.9))
            self.resize(max(w, self.minimumWidth()), max(h, self.minimumHeight()))
            self.move(screen.center() - self.rect().center())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.overlay.setGeometry(self.centralWidget().rect())
        self.toast.reposition()

    def closeEvent(self, e: QCloseEvent) -> None:
        if self.ctx.engine.active_scans():
            from .dialogs import confirm

            if not confirm(self, "Остановить сканирование?",
                           "Сейчас выполняются сканы. При выходе они будут остановлены, "
                           "собранные частичные результаты сохранятся.", "Выйти", danger=True):
                e.ignore()
                return
        e.accept()

    # ------------------------------------------------------------ drag & drop
    def _drop_path(self, e: QDragEnterEvent | QDropEvent) -> Path | None:
        md = e.mimeData()
        if not md.hasUrls() or len(md.urls()) != 1 or not md.urls()[0].isLocalFile():
            return None
        p = Path(md.urls()[0].toLocalFile())
        return p if p.is_file() else None

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if self._current == "welcome" or not self.ctx.settings.get("disclaimer_accepted"):
            return
        path = self._drop_path(e)
        if path is None:
            return
        limit = int(self.ctx.settings.get("max_file_mb", 100))
        self.overlay.set_message("Отпусти файл для анализа метаданных",
                                 f"Изображения, PDF и документы · до {limit} МБ")
        self.overlay.setGeometry(self.centralWidget().rect())
        self.overlay.raise_()
        self.overlay.show()
        e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self.overlay.hide()

    def dropEvent(self, e: QDropEvent) -> None:
        self.overlay.hide()
        path = self._drop_path(e)
        if path is None:
            return
        e.acceptProposedAction()
        self.start_file_scan(str(path))

    def start_file_scan(self, path: str) -> None:
        from ..core.schema import TargetType

        tools = self.ctx.tools_for(TargetType.FILE)
        if not tools:
            self.toast.show_message("ExifTool не установлен или отключён в настройках", "error")
            return
        limit = int(self.ctx.settings.get("max_file_mb", 100))
        if Path(path).stat().st_size > limit * 1_048_576:
            self.toast.show_message(f"Файл больше {limit} МБ", "error")
            return
        self.ctx.start_scan(path, TargetType.FILE, tools)
