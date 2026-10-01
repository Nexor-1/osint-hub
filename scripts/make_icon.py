"""Render the app icon (same artwork as the window icon) into build/app.ico."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice, QSize
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)  # QPixmap needs a QGuiApplication
    from app.main import app_icon

    icon = app_icon()
    images = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = icon.pixmap(QSize(size, size))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pm.toImage().save(buf, "PNG")
        images.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
    out = ROOT / "build" / "app.ico"
    out.parent.mkdir(exist_ok=True)
    images[-1].save(out, format="ICO", sizes=[im.size for im in images], append_images=images[:-1])
    print(f"icon -> {out}")
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
