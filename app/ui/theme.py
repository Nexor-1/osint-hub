"""Design tokens from the mockups (design/OSINT_Hub_Mockups.html) and the global stylesheet.

All colours, radii and sizes live here; widgets refer to tokens or to QSS
dynamic properties (``variant``, ``role``, ``card`` …) instead of hard-coding
styles, so the look stays consistent with the design system screen.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ..config import resource_dir

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- colour tokens
BG = "#0F1115"
SURFACE = "#171A21"
HOVER = "#1C2029"
BORDER = "#262A33"
TEXT = "#E6E8EB"
SUB = "#8A8F98"
DISABLED = "#5A5F69"
ACCENT = "#7C6CF2"
ACCENT_HOVER = "#8A7CF7"
ACCENT_PRESSED = "#6557D6"
ACCENT_SOFT = "#AA9EFA"
SUCCESS = "#3FB68B"
WARNING = "#E5A94B"
ERROR = "#E5484D"
ERROR_SOFT = "#EF7175"

INPUT_BG = "#12151B"
INPUT_BORDER = "#343943"
BUTTON_BG = "#20242C"
BUTTON_HOVER = "#282C36"
SUBTLE_BG = "#1B1E25"
LOG_BG = "#14171D"
RAIL_ACTIVE_BG = "#27233D"
RAIL_ACTIVE_FG = "#C2BAFD"

# Badge variants: background, foreground
BADGES = {
    "neutral": ("#252A34", "#ABB0BA"),
    "muted": ("#242833", SUB),
    "success": ("#16352D", SUCCESS),
    "warn": ("#392C19", WARNING),
    "error": ("#381D22", ERROR_SOFT),
    "active": ("#2A2547", ACCENT_SOFT),
}

# Tool tile/icon tints: background, foreground
TINTS = {
    "violet": ("#24243A", "#AA9EFA"),
    "green": ("#1A332B", "#62CAA4"),
    "gold": ("#382D20", "#ECC06B"),
    "blue": ("#202D3C", "#81AAD9"),
    "pink": ("#382533", "#D594BE"),
}

FONT_UI = "Inter"
FONT_MONO = "JetBrains Mono"
RADIUS_CARD = 12
RADIUS_CONTROL = 8


def load_fonts() -> None:
    """Register bundled Inter / JetBrains Mono (OFL) with Qt."""
    folder = resource_dir() / "app" / "ui" / "fonts"
    for ttf in sorted(folder.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(ttf)) < 0:
            log.warning("font not loaded: %s", ttf)


def ui_font(size: int = 14, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(FONT_UI)
    f.setFamilies([FONT_UI, "Segoe UI", "Arial"])
    f.setPixelSize(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def mono_font(size: int = 13) -> QFont:
    f = QFont(FONT_MONO)
    f.setFamilies([FONT_MONO, "Cascadia Mono", "Consolas"])
    f.setPixelSize(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def apply(app: QApplication) -> None:
    """Install fonts, palette and the global stylesheet."""
    load_fonts()
    app.setStyle("Fusion")
    app.setFont(ui_font())
    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.Base, INPUT_BG),
        (QPalette.ColorRole.AlternateBase, SURFACE), (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT), (QPalette.ColorRole.Button, BUTTON_BG),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.ToolTipBase, SUBTLE_BG),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, "#666C77"),
        (QPalette.ColorRole.Link, ACCENT_SOFT),
    ]:
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(DISABLED))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(DISABLED))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(DISABLED))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    badge_rules = "\n".join(
        f'QLabel[badge="{name}"] {{ background:{bg}; color:{fg}; }}' for name, (bg, fg) in BADGES.items()
    )
    return f"""
* {{ outline: none; }}
QWidget {{ color:{TEXT}; font-family:"{FONT_UI}","Segoe UI"; font-size:14px; }}
QMainWindow, QWidget#Root, QWidget[page="true"], QStackedWidget#MainStack {{ background:{BG}; }}
QStackedWidget {{ background:transparent; }}
QScrollArea {{ background:transparent; border:none; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QToolTip {{ background:{SUBTLE_BG}; color:{TEXT}; border:1px solid {INPUT_BORDER}; padding:6px 8px; border-radius:6px; }}

/* ---------- surfaces ---------- */
QFrame[card="true"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:{RADIUS_CARD}px; }}
QFrame[card="true"][hoverable="true"]:hover {{ background:{HOVER}; border-color:#3B4050; }}
QFrame[card="true"][state="error"] {{ border-color:#533039; }}
QFrame[card="true"][state="selected"] {{ background:{HOVER}; border-color:#3B4050; }}
QFrame[card="true"][state="disabled"] {{ background:{SURFACE}; }}
QFrame[card="true"][tone="log"] {{ background:{LOG_BG}; }}
QFrame[card="true"][tone="subtle"] {{ background:#15181E; }}
QFrame[card="true"][tone="modal"] {{ background:{SUBTLE_BG}; border-color:#353945; border-radius:14px; }}
QFrame[hint="true"] {{ background:#211F30; border:1px solid #39324E; border-radius:10px; }}
QFrame[notice="true"] {{ background:#1B1F27; border:1px solid #333746; border-radius:9px; }}
QFrame[keynote="true"] {{ background:transparent; border:1px solid {BORDER}; border-radius:8px; }}
QFrame[toast="true"] {{ background:#1D2825; border:1px solid #2C5545; border-radius:9px; }}
QFrame[toast="error"] {{ background:#2A1D21; border:1px solid #533039; border-radius:9px; }}
QFrame[rule="true"] {{ background:{BORDER}; border:none; max-height:1px; min-height:1px; }}
QFrame[searchbox="true"] {{ background:{SURFACE}; border:1px solid #343946; border-radius:12px; }}
QFrame[searchbox="true"][focused="true"] {{ border-color:{ACCENT}; }}
QFrame[dropzone="true"] {{ background:rgba(23,26,33,245); border:2px dashed #8173E6; border-radius:18px; }}
QFrame[tablehead="true"] {{ background:{SUBTLE_BG}; border:none; border-bottom:1px solid {BORDER};
    border-top-left-radius:{RADIUS_CARD}px; border-top-right-radius:{RADIUS_CARD}px; }}
QFrame[tablerow="true"] {{ background:transparent; border:none; border-bottom:1px solid {BORDER}; }}
QFrame[tablerow="true"][last="true"] {{ border-bottom:none; }}
QFrame[tablerow="true"][clickable="true"]:hover {{ background:{HOVER}; }}

/* ---------- text roles ---------- */
QLabel {{ background:transparent; }}
QLabel[role="eyebrow"] {{ color:{SUB}; font-size:12px; font-weight:600; }}
QLabel[role="pagetitle"] {{ font-size:28px; font-weight:600; }}
QLabel[role="hero"] {{ font-size:29px; font-weight:600; }}
QLabel[role="h1"] {{ font-size:28px; font-weight:600; }}
QLabel[role="section"] {{ font-size:18px; font-weight:500; }}
QLabel[role="cardtitle"] {{ font-size:15px; font-weight:500; }}
QLabel[role="tiletitle"] {{ font-size:14px; font-weight:600; }}
QLabel[role="lead"] {{ color:{SUB}; }}
QLabel[role="sub"] {{ color:{SUB}; font-size:12px; }}
QLabel[role="disabled"] {{ color:{DISABLED}; font-size:12px; }}
QLabel[role="mono"] {{ font-family:"{FONT_MONO}"; font-size:13px; }}
QLabel[role="big"] {{ font-size:38px; font-weight:600; }}
QLabel[role="pct"] {{ color:#A99DFD; font-size:22px; font-weight:600; }}
QLabel[role="error"] {{ color:{ERROR_SOFT}; font-size:12px; }}
QLabel[role="accent"] {{ color:#BCB4FF; font-size:12px; }}
QLabel[role="hinttext"] {{ color:#D0CAFD; }}
QLabel[role="toast"] {{ color:#C9EADC; font-size:12px; }}
QLabel[role="noticetext"] {{ color:#BDC0C8; }}
QLabel[role="sitelogo"] {{ background:#2B3040; color:#C0C9DF; border-radius:9px; font-weight:700; font-size:15px; }}

/* ---------- badges ---------- */
QLabel[badge] {{ font-size:11px; font-weight:600; padding:4px 9px; border-radius:6px; }}
{badge_rules}

/* ---------- buttons ---------- */
QPushButton, QToolButton {{ background:{BUTTON_BG}; border:1px solid {BORDER}; border-radius:{RADIUS_CONTROL}px;
    min-height:36px; padding:0 15px; font-weight:500; color:{TEXT}; }}
QPushButton:hover, QToolButton:hover {{ background:{BUTTON_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background:#2E3340; }}
QPushButton:focus {{ border-color:{ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ color:{DISABLED}; background:#1A1D23; }}
QPushButton[variant="primary"] {{ background:{ACCENT}; border-color:{ACCENT}; color:#FFFFFF; }}
QPushButton[variant="primary"]:hover {{ background:{ACCENT_HOVER}; border-color:{ACCENT_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background:{ACCENT_PRESSED}; border-color:{ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:disabled {{ background:#3A3466; border-color:#3A3466; color:#9A93C9; }}
QPushButton[variant="text"], QToolButton[variant="text"] {{ background:transparent; border-color:transparent; color:{SUB}; }}
QPushButton[variant="text"]:hover, QToolButton[variant="text"]:hover {{ background:#222633; color:{TEXT}; }}
QPushButton[variant="danger"] {{ color:#F1777B; }}
QPushButton[variant="danger"]:hover {{ background:#2A1D21; }}
QPushButton[size="sm"], QToolButton[size="sm"] {{ min-height:30px; max-height:32px; padding:0 12px; font-size:12px; }}
QPushButton[size="lg"] {{ min-height:44px; padding:0 20px; }}
QPushButton[variant="icon"], QToolButton[variant="icon"] {{ background:transparent; border:none; padding:0; min-height:28px;
    min-width:28px; border-radius:6px; }}
QPushButton[variant="icon"]:hover, QToolButton[variant="icon"]:hover {{ background:#222633; }}
QPushButton[variant="tab"] {{ background:transparent; border:none; border-radius:0; min-height:40px; padding:0 15px;
    color:{SUB}; font-size:13px; font-weight:400; border-bottom:2px solid transparent; }}
QPushButton[variant="tab"]:hover {{ color:{TEXT}; }}
QPushButton[variant="tab"]:checked {{ color:{TEXT}; border-bottom:2px solid {ACCENT}; }}
QPushButton[variant="segment"] {{ background:transparent; border:none; border-radius:6px; min-height:32px; padding:0 15px;
    color:{SUB}; font-size:12px; font-weight:500; }}
QPushButton[variant="segment"]:checked {{ background:#292D36; color:{TEXT}; }}
QPushButton[variant="nav"] {{ background:transparent; border:none; border-radius:7px; min-height:42px; padding:0 13px;
    color:{SUB}; text-align:left; font-weight:400; }}
QPushButton[variant="nav"]:hover {{ background:#262A33; color:{TEXT}; }}
QPushButton[variant="nav"]:checked {{ background:#28243E; color:#C3BBFF; }}
QPushButton[variant="format"] {{ background:transparent; border:1px solid {BORDER}; border-radius:9px; min-height:56px;
    padding:0 14px; text-align:left; color:{SUB}; font-weight:400; }}
QPushButton[variant="format"]:checked {{ border-color:{ACCENT}; background:#28243F; color:{TEXT}; }}
QPushButton[variant="chip"] {{ background:transparent; border:1px solid {BORDER}; border-radius:7px; min-height:26px;
    padding:0 9px; color:{SUB}; font-size:12px; font-weight:400; }}
QPushButton[variant="chip"]:hover {{ color:{TEXT}; border-color:#3B4050; }}
QFrame[segmented="true"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:9px; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit[editable="true"] {{ background:{INPUT_BG}; border:1px solid {INPUT_BORDER};
    border-radius:{RADIUS_CONTROL}px; padding:0 12px; min-height:38px; color:{TEXT};
    selection-background-color:{ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{ACCENT}; }}
QLineEdit:disabled {{ color:{DISABLED}; }}
QFrame[inputbox="true"] {{ background:{INPUT_BG}; border:1px solid {INPUT_BORDER}; border-radius:{RADIUS_CONTROL}px;
    min-height:38px; max-height:40px; }}
QFrame[inputbox="true"][focused="true"] {{ border-color:{ACCENT}; }}
QLineEdit[role="bare"] {{ background:transparent; border:none; padding:0; min-height:36px; }}
QLineEdit[role="search"] {{ background:transparent; border:none; font-size:15px; padding:0; min-height:44px; }}
QLineEdit[role="mono"] {{ font-family:"{FONT_MONO}"; font-size:13px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width:0; border:none; }}
QComboBox::drop-down {{ border:none; width:24px; }}
QComboBox QAbstractItemView {{ background:{SUBTLE_BG}; border:1px solid {INPUT_BORDER}; selection-background-color:#28243E;
    outline:none; padding:4px; }}

/* ---------- menus ---------- */
QMenu {{ background:{SUBTLE_BG}; border:1px solid #353945; border-radius:10px; padding:6px; }}
QMenu::item {{ padding:8px 28px 8px 12px; border-radius:6px; color:{TEXT}; }}
QMenu::item:selected {{ background:#28243E; color:#E3DFFF; }}
QMenu::item:disabled {{ color:{DISABLED}; }}
QMenu::indicator {{ width:14px; height:14px; left:6px; }}
QMenu::separator {{ height:1px; background:{BORDER}; margin:6px 4px; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
QScrollBar::handle:vertical {{ background:#2E333D; border-radius:3px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:#3D4350; }}
QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:#2E333D; border-radius:3px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background:none; border:none; width:0; height:0; }}

/* ---------- tables ---------- */
QTableView {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:{RADIUS_CARD}px; gridline-color:transparent;
    selection-background-color:{HOVER}; selection-color:{TEXT}; alternate-background-color:{SURFACE}; }}
QTableView::item {{ border-bottom:1px solid {BORDER}; padding:0 6px; }}
QTableView::item:hover {{ background:{HOVER}; }}
QHeaderView {{ background:transparent; }}
QHeaderView::section {{ background:{SUBTLE_BG}; color:{SUB}; font-size:12px; border:none;
    border-bottom:1px solid {BORDER}; padding:0 12px; height:40px; }}
QHeaderView::section:first {{ border-top-left-radius:{RADIUS_CARD}px; }}
QHeaderView::section:last {{ border-top-right-radius:{RADIUS_CARD}px; }}
QTableCornerButton::section {{ background:{SUBTLE_BG}; border:none; }}

/* ---------- text views ---------- */
QPlainTextEdit, QTextBrowser {{ background:transparent; border:none; color:#949AA7;
    font-family:"{FONT_MONO}"; font-size:11px; selection-background-color:{ACCENT}; }}
QPlainTextEdit[role="raw"] {{ background:{INPUT_BG}; border:1px solid {BORDER}; border-radius:{RADIUS_CARD}px;
    color:#C5C9D2; font-size:12px; padding:10px; }}
QDialog {{ background:{BG}; }}
"""


def polish(w: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property change."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def set_prop(w: QWidget, name: str, value: object) -> None:
    if w.property(name) != value:
        w.setProperty(name, value)
        polish(w)


def dark_title_bar(widget: QWidget) -> None:
    """Make the native Windows title bar match the dark theme (Win 10 20H1+ / Win 11)."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))  # immersive dark mode

        def colorref(hex_: str) -> ctypes.c_int:
            c = QColor(hex_)
            return ctypes.c_int(c.red() | (c.green() << 8) | (c.blue() << 16))

        cap, txt, border = colorref("#0B0D11"), colorref(SUB), colorref("#1B1E25")
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), 4)    # caption colour (Win 11)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), 4)    # caption text colour
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)  # border colour
    except Exception:  # older Windows: keep the default title bar
        log.debug("dark title bar not available", exc_info=True)


def map_dir() -> Path:
    return resource_dir() / "app" / "ui" / "map"
