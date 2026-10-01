"""Mockup 07: ExifTool result — preview, metadata cards and a Leaflet map."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, QUrlQuery
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from ...adapters.exiftool import ExifToolAdapter
from ...config import APP_REPO, APP_VERSION
from ...core.storage import ScanRecord
from .. import fmt, icons, theme
from ..dialogs import open_export
from ..widgets import Card, KeyValueGrid, PageHeader, button, hbox, icon_label, label, vbox
from .base import Page

IMAGE_TYPES = {"JPEG", "PNG", "GIF", "BMP", "WEBP", "TIFF", "HEIC", "HEIF"}


class Preview(QLabel):
    """Rounded, cover-cropped image preview (or a large file icon)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(308)
        self._pm: QPixmap | None = None

    def set_file(self, path: str | None, is_image: bool) -> None:
        self._pm = None
        if path and is_image and Path(path).exists():
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            reader.setScaledSize(reader.size().scaled(QSize(1200, 1200), Qt.AspectRatioMode.KeepAspectRatio)
                                 if reader.size().width() > 1200 else reader.size())
            img = reader.read()
            if not img.isNull():
                self._pm = QPixmap.fromImage(img)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.setClipPath(path)
        p.fillRect(r, QColor(theme.SUBTLE_BG if self._pm is None else "#243641"))
        if self._pm is not None:
            scaled = self._pm.scaled(self.size() * self.devicePixelRatioF(),
                                     Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            sw, sh = scaled.width() / scaled.devicePixelRatio(), scaled.height() / scaled.devicePixelRatio()
            p.drawPixmap(int((self.width() - sw) / 2), int((self.height() - sh) / 2), scaled)
        else:
            pm = icons.pixmap("file-text", theme.DISABLED, 64, 1.2)
            p.drawPixmap(int(r.center().x() - 32), int(r.center().y() - 32), pm)


class MapView(QWidget):
    """Lazy QWebEngineView with the local Leaflet page."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(300, 200)
        self._view = None
        self._lay = vbox(self)
        self._fallback = label("Карта недоступна: компонент QtWebEngine не загружен", "sub", wrap=True)
        self._fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("MapView { background:#1B242B; border:1px solid #303C43; border-radius:8px; }")

    def show_point(self, lat: float, lon: float) -> None:
        if self._view is None:
            try:
                from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
                from PySide6.QtWebEngineWidgets import QWebEngineView
            except ImportError:
                self._lay.addWidget(self._fallback)
                return

            class Page(QWebEnginePage):
                def acceptNavigationRequest(self, url, nav_type, is_main):  # noqa: N802
                    if url.scheme() in ("http", "https") and nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                        QDesktopServices.openUrl(url)  # attribution links open in the user's browser
                        return False
                    return super().acceptNavigationRequest(url, nav_type, is_main)

            profile = QWebEngineProfile.defaultProfile()
            # OSM tile usage policy asks clients to identify themselves.
            profile.setHttpUserAgent(f"{profile.httpUserAgent()} OSINTHub/{APP_VERSION} (+{APP_REPO})")
            view = QWebEngineView(self)
            view.setPage(Page(profile, view))
            from PySide6.QtWebEngineCore import QWebEngineSettings

            # The page is a local file (bundled Leaflet); tiles come from tile.openstreetmap.org.
            s = view.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
            view.page().setBackgroundColor(Qt.GlobalColor.transparent)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self._lay.addWidget(view)
            self._view = view
        url = QUrl.fromLocalFile(str(theme.map_dir() / "leaflet.html"))
        q = QUrlQuery()
        q.addQueryItem("lat", f"{lat:.6f}")
        q.addQueryItem("lon", f"{lon:.6f}")
        url.setQuery(q)
        self._view.load(url)


class MetaCard(Card):
    def __init__(self, title: str, icon_name: str) -> None:
        super().__init__(padding=(20, 18, 20, 18), spacing=0)
        self.setMinimumHeight(146)
        head = hbox(spacing=8)
        head.addWidget(icon_label(icon_name, theme.SUB, 16))
        head.addWidget(label(title, "cardtitle"))
        head.addStretch(1)
        self.lay.addLayout(head)
        self.lay.addSpacing(14)
        self.kv = KeyValueGrid()
        self.lay.addWidget(self.kv)
        self.empty = label("Нет данных в файле", "sub")
        self.lay.addWidget(self.empty)
        self.lay.addStretch(1)

    def fill(self, rows: list[tuple[str, str]], mono_keys: set[str] = frozenset()) -> None:
        self.kv.clear()
        for k, v in rows:
            self.kv.add(k, v, mono=k in mono_keys)
        self.empty.setVisible(not rows)


class ExifPage(Page):
    title = "ExifTool"
    rail_key = "home"

    def __init__(self, ctx) -> None:
        super().__init__(ctx, margins=(60, 48, 60, 40))
        self.scan: ScanRecord | None = None
        self.path: str | None = None
        self.gps: dict | None = None

        self.header = PageHeader("Результат инструмента", "Метаданные файла", "")
        self.header.actions.addWidget(button("К результатам", "arrow-left", on_click=self._back))
        self.header.actions.addWidget(button("Экспорт", "download", variant="primary", on_click=self._export))
        self.body.addWidget(self.header)
        self.body.addSpacing(28)

        self.grid_host = QWidget()
        self.body.addWidget(self.grid_host)
        self.layout_grid = hbox(self.grid_host, spacing=24)

        # preview card
        self.preview_card = Card(padding=16, spacing=0)
        self.preview_card.setFixedWidth(380)
        self.preview = Preview()
        self.preview_card.lay.addWidget(self.preview)
        line = hbox(spacing=10)
        line.setContentsMargins(2, 14, 2, 2)
        self.file_icon = QLabel()
        self.file_icon.setFixedSize(30, 30)
        self.file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_icon.setStyleSheet("background:#202D3C; border-radius:8px;")
        self.file_icon.setPixmap(icons.pixmap("image", "#81AAD9", 16))
        line.addWidget(self.file_icon)
        col = vbox(spacing=1)
        self.file_name = label("", None)
        self.file_name.setStyleSheet("font-weight:600;")
        self.file_meta = label("", "sub")
        col.addWidget(self.file_name)
        col.addWidget(self.file_meta)
        line.addLayout(col, 1)
        self.more = button("", "ellipsis", variant="icon", tooltip="Действия с файлом")
        menu = QMenu(self.more)
        menu.addAction(icons.icon("folder-open", theme.TEXT, 16), "Показать в папке", self._reveal)
        menu.addAction(icons.icon("arrow-up-right", theme.TEXT, 16), "Открыть файл", self._open_file)
        menu.addAction(icons.icon("copy", theme.TEXT, 16), "Копировать путь", self._copy_path)
        menu.addSeparator()
        menu.addAction(icons.icon("braces", theme.TEXT, 16), "Все теги (сырой вывод)",
                       lambda: self.ctx.go("results", scan_id=self.scan.id, tab="raw") if self.scan else None)
        self.more.setMenu(menu)
        self.more.setStyleSheet("QPushButton::menu-indicator { image:none; width:0; }")
        line.addWidget(self.more)
        self.preview_card.lay.addLayout(line)
        self.preview_card.lay.addStretch(1)
        self.layout_grid.addWidget(self.preview_card, 0, Qt.AlignmentFlag.AlignTop)

        # metadata cards + map
        right = vbox(spacing=12)
        self.layout_grid.addLayout(right, 1)
        r1, r2 = hbox(spacing=12), hbox(spacing=12)
        self.c_device = MetaCard("Устройство", "camera")
        self.c_date = MetaCard("Дата и время", "calendar")
        self.c_loc = MetaCard("Местоположение", "map-pin")
        self.c_author = MetaCard("Автор и программа", "pen")
        r1.addWidget(self.c_device, 1)
        r1.addWidget(self.c_date, 1)
        r2.addWidget(self.c_loc, 1)
        r2.addWidget(self.c_author, 1)
        right.addLayout(r1)
        right.addLayout(r2)

        self.map_card = Card(padding=(19, 17, 19, 17), spacing=17, horizontal=True)
        self.map_card.setMinimumHeight(236)
        self.map = MapView()
        self.map_card.lay.addWidget(self.map, 55)
        info = vbox(spacing=0)
        info.addSpacing(2)
        info.addWidget(label("Точка на карте", "cardtitle"))
        info.addSpacing(16)
        self.map_note = label("Координаты сохранены в EXIF файла. Источник местоположения — GPS устройства.",
                              "sub", wrap=True)
        info.addWidget(self.map_note)
        info.addSpacing(15)
        crow = hbox(spacing=8)
        crow.addWidget(icon_label("map-pin", theme.ACCENT, 16))
        self.coord = label("", "mono", selectable=True)
        crow.addWidget(self.coord, 1)
        info.addLayout(crow)
        info.addSpacing(16)
        brow = hbox(spacing=8)
        brow.addWidget(button("Скопировать координаты", "copy", size="sm", on_click=self._copy_coords))
        brow.addWidget(button("OpenStreetMap", "arrow-up-right", variant="text", size="sm", on_click=self._open_osm))
        brow.addStretch(1)
        info.addLayout(brow)
        info.addStretch(1)
        self.map_card.lay.addLayout(info, 45)
        right.addWidget(self.map_card)
        self.no_gps = Card(padding=(19, 17, 19, 17), spacing=10, horizontal=True)
        self.no_gps.lay.addWidget(icon_label("map-pin", theme.DISABLED, 18))
        self.no_gps.lay.addWidget(label("В файле нет GPS-координат — точку на карте показать нельзя.", "sub"), 1)
        right.addWidget(self.no_gps)
        right.addStretch(1)

    # ------------------------------------------------------------
    def on_enter(self, scan_id: int | None = None, **kwargs) -> None:
        if scan_id is None:
            return
        scan = self.ctx.storage.get_scan(scan_id)
        res = scan.results.get("exiftool") if scan else None
        if scan is None or res is None:
            self.ctx.go("results", scan_id=scan_id)
            return
        self.scan, self.path = scan, scan.target
        raw = res.raw or {}
        info = ExifToolAdapter.file_summary(raw)
        findings = res.findings
        sections: dict[str, list] = {"device": [], "datetime": [], "location": [], "author": []}
        self.gps = None
        for f in findings:
            sec = f.extra.get("section")
            if f.type == "geo":
                self.gps = f.extra
                sections["location"].append(("Координаты", f.value))
            elif sec in sections:
                value = fmt.exif_date(f.value) if f.type == "datetime" else f.value
                sections[sec].append((f.extra.get("field", f.type), value))
        self.c_device.fill(sections["device"])
        self.c_date.fill(sections["datetime"])
        self.c_loc.fill(sections["location"], {"Координаты"})
        self.c_author.fill(sections["author"])

        kinds = [k for k, rows in (("устройства", sections["device"]), ("времени", sections["datetime"]),
                                   ("местоположения", sections["location"]), ("автора", sections["author"])) if rows]
        if not kinds:
            lead = "ExifTool · значимых метаданных не найдено"
        elif len(kinds) == 1:
            lead = f"ExifTool · обнаружены данные {kinds[0]}"
        else:
            lead = f"ExifTool · обнаружены данные {', '.join(kinds[:-1])} и {kinds[-1]}"
        if res.status == "error":
            lead = f"ExifTool · ошибка: {res.error}"
        self.header.set_lead(lead)

        self.file_name.setText(info["name"] or Path(scan.target).name)
        meta = " · ".join(x for x in (info["type"], info["size"].replace(".", ",") if info["size"] else "",
                                       info["dimensions"].replace("x", " × ") + " px" if info["dimensions"] else "") if x)
        self.file_meta.setText(meta)
        is_image = (info["type"] or "").upper() in IMAGE_TYPES
        self.file_icon.setPixmap(icons.pixmap("image" if is_image else "file-text", "#81AAD9", 16))
        self.preview.set_file(scan.target, is_image)

        if self.gps:
            lat, lon = float(self.gps["lat"]), float(self.gps["lon"])
            self.coord.setText(fmt.coord(lat, lon))
            self.map_card.show()
            self.no_gps.hide()
            self.map.show_point(lat, lon)
        else:
            self.map_card.hide()
            self.no_gps.show()
        self.scroll_top()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        narrow = self.width() < 1180
        self.preview_card.setFixedWidth(290 if narrow else 380)
        self.preview.setMinimumHeight(220 if narrow else 308)

    # ------------------------------------------------------------ actions
    def _back(self) -> None:
        if self.scan:
            self.ctx.go("results", scan_id=self.scan.id)

    def _export(self) -> None:
        if self.scan:
            open_export(self, self.ctx, self.scan.id)

    def _copy_coords(self) -> None:
        if self.gps:
            QGuiApplication.clipboard().setText(f"{self.gps['lat']:.6f}, {self.gps['lon']:.6f}")
            self.ctx.toast("Координаты скопированы")

    def _open_osm(self) -> None:
        if self.gps:
            la, lo = self.gps["lat"], self.gps["lon"]
            QDesktopServices.openUrl(QUrl(f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map=16/{la}/{lo}"))

    def _reveal(self) -> None:
        if self.path and Path(self.path).exists():
            # explorer.exe /select,<path> — argument list, no shell.
            subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(self.path)}"])
        else:
            self.ctx.toast("Файл больше не существует по исходному пути", "error")

    def _open_file(self) -> None:
        if self.path and Path(self.path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
        else:
            self.ctx.toast("Файл больше не существует по исходному пути", "error")

    def _copy_path(self) -> None:
        if self.path:
            QGuiApplication.clipboard().setText(self.path)
            self.ctx.toast("Путь скопирован")
