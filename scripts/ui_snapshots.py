"""Render every page with demo data and save PNG snapshots (visual check against the mockups).

    python scripts/ui_snapshots.py [out_dir] [--size 1440x900] [--live]

Uses a temporary data directory seeded from tests/fixtures, so your real
history is untouched. ``--live`` also starts a real Holehe+Sherlock scan to
capture the live scan page.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["OSINTHUB_DATA_DIR"] = tempfile.mkdtemp(prefix="osinthub-ui-")
FIX = ROOT / "tests" / "fixtures"


def seed(storage, settings) -> dict[str, int]:
    from app.adapters.base import registry
    from app.core.schema import Status, ToolResult, utcnow

    def add(target, ttype, tools_raw, errors=None):
        sid = storage.create_scan(target, ttype, list(tools_raw))
        for tool, raw in tools_raw.items():
            a = registry()[tool](settings)
            res = ToolResult(tool, target, Status.DONE.value, utcnow(), utcnow(), a.parse_output(raw), raw,
                             target_type=ttype)
            if errors and tool in errors:
                res.status, res.error = Status.ERROR.value, errors[tool]
                res.findings = res.findings[:3]
            storage.save_result(sid, res, "12:00:00 [INFO] demo")
        return sid

    load = lambda n: json.loads((FIX / n).read_text(encoding="utf-8"))  # noqa: E731
    ids = {}
    ids["domain"] = add("example.com", "domain", {"spiderfoot": load("spiderfoot_raw.json")})
    ids["phone"] = add("+16502530000", "phone", {"phoneinfoga": load("phoneinfoga_raw.json")})
    raw_exif = load("exiftool_raw.json")
    raw_exif["file"] = str(FIX / "files" / "trip_тест.jpg")
    ids["file"] = add(raw_exif["file"], "file", {"exiftool": raw_exif})
    ids["username"] = add("octocat", "username", {"sherlock": load("sherlock_raw.json")})
    email_sf = {"events": [
        {"type": "Username", "data": "marina_v", "module": "sfp_emailformat", "source": "x"},
        {"type": "Email Address", "data": "m.voronina@northwind.example", "module": "sfp_pgp", "source": "x"},
        {"type": "Domain Name", "data": "northwind.example", "module": "sfp_dnsresolve", "source": "x"},
        {"type": "Account on External Site", "data": "GitHub (Category: coding)\n<SFURL>https://github.com/marina_v</SFURL>",
         "module": "sfp_accounts", "source": "x"},
    ]}
    ids["email"] = add("marina.voronina@example.org", "email",
                       {"holehe": load("holehe_sample.json"), "spiderfoot": email_sf},
                       errors=None)
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(ROOT / "build" / "snapshots"))
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    w, h = map(int, args.size.split("x"))

    from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    from app.config import Settings
    from app.core.runner import ScanEngine
    from app.core.schema import TargetType
    from app.core.storage import Storage
    from app.ui import theme
    from app.ui.bridge import EngineBridge
    from app.ui.context import AppContext
    from app.ui.main_window import MainWindow

    theme.apply(app)
    settings = Settings()
    storage = Storage()
    engine = ScanEngine(settings, storage)
    bridge = EngineBridge(engine)
    engine.start()
    ids = seed(storage, settings)
    ctx = AppContext(settings, storage, engine, bridge)
    win = MainWindow(ctx)
    win.show()

    def wait(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def snap(name: str, ms: int = 500) -> None:
        wait(ms)
        win.grab().save(str(out / f"{name}.png"))
        print("saved", name, flush=True)

    wait(100)
    win.resize(w, h)  # after show: the window applies its own default size on first show
    snap("01_welcome")
    settings.set("disclaimer_accepted", True)
    win.navigate("home")
    snap("02_home")
    page = win.pages["home"]
    page.input.setText("marina.voronina@example.org")
    snap("03_home_email", 700)
    win.overlay.setGeometry(win.centralWidget().rect())
    win.overlay.raise_()
    win.overlay.show()
    snap("04_drop")
    win.overlay.hide()
    page.input.clear()

    if args.live:
        ctx.start_scan("test@example.com", TargetType.EMAIL, ["holehe", "spiderfoot"])
        snap("05_scan_live", 6000)
    win.navigate("results", scan_id=ids["email"])
    snap("06_results")
    win.navigate("results", scan_id=ids["domain"])
    snap("06b_results_domain")
    win.pages["results"].tabs.set_current("raw")
    win.pages["results"]._on_tab("raw")
    snap("06c_results_raw")
    win.navigate("exif", scan_id=ids["file"])
    snap("07_exif", 4000)
    win.navigate("sherlock", scan_id=ids["username"])
    snap("08_sherlock", 800)
    win.navigate("history")
    snap("09_history")
    win.navigate("reports")
    snap("10_reports")
    for sec in ("tools", "keys", "general", "storage", "about"):
        win.navigate("settings", section=sec)
        snap(f"11_settings_{sec}")
    win.resize(1100, 760)
    win.navigate("results", scan_id=ids["email"])
    snap("12_results_narrow", 700)
    win.navigate("home")
    snap("12_home_narrow", 700)

    if args.live:
        # Let the live scan finish (or time out) before shutting down.
        deadline = time.time() + 120
        while engine.active_scans() and time.time() < deadline:
            wait(500)
        win.navigate("history")
        snap("13_history_after_live")
    engine.stop()
    storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
