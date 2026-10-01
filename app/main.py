"""OSINT Hub entry point."""

from __future__ import annotations

import logging
import logging.handlers
import multiprocessing
import os
import sys
import traceback


def setup_logging() -> None:
    from .config import data_dir

    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "osinthub.log", maxBytes=2_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())


def app_icon():
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

    from .ui import icons

    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2A2548"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)
        inner = icons.render_svg(icons._svg("brand", "#B4A9FF", 2.0), int(size * 0.62), int(size * 0.62))
        inner.setDevicePixelRatio(1.0)
        p.drawPixmap(int(size * 0.19), int(size * 0.19), inner.scaled(int(size * 0.62), int(size * 0.62),
                                                                      Qt.AspectRatioMode.KeepAspectRatio,
                                                                      Qt.TransformationMode.SmoothTransformation))
        p.end()
        ic.addPixmap(pm)
    return ic


def main() -> int:
    multiprocessing.freeze_support()
    # A windowed (no console) build has no stdout/stderr; some libraries write to them.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if "--selftest" in sys.argv:
        from .selftest import run

        i = sys.argv.index("--selftest")
        return run(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    setup_logging()
    log = logging.getLogger("osinthub")

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    # Required before QApplication when QtWebEngine (map) is used later.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-logging")

    if sys.platform == "win32":
        import ctypes

        # Own taskbar group/icon instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OSINTHub.Desktop.1")

    app = QApplication(sys.argv)
    from .config import APP_NAME, APP_TITLE, APP_VERSION, Settings
    from .core.runner import ScanEngine
    from .core.storage import Storage
    from .ui import theme
    from .ui.bridge import EngineBridge
    from .ui.context import AppContext
    from .ui.main_window import MainWindow

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    theme.apply(app)
    app.setWindowIcon(app_icon())

    def excepthook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception:\n%s", text)
        QMessageBox.critical(None, APP_TITLE, f"Непредвиденная ошибка:\n{exc}\n\nПодробности записаны в журнал.")

    sys.excepthook = excepthook

    settings = Settings()
    storage = Storage()
    engine = ScanEngine(settings, storage)
    bridge = EngineBridge(engine)
    engine.start()
    ctx = AppContext(settings, storage, engine, bridge)
    window = MainWindow(ctx)
    window.show()
    log.info("%s %s started", APP_TITLE, APP_VERSION)
    code = app.exec()
    engine.stop()
    storage.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
