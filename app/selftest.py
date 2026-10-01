"""Installation self-test: ``OSINTHub.exe --selftest [report.json]``.

Runs without a window and checks that every bundled tool can actually
start from this installation (no network needed):

* each adapter is discovered and reports itself available;
* ExifTool extracts GPS from a freshly generated JPEG;
* PhoneInfoga and SpiderFoot print their versions;
* Holehe modules and the Sherlock site list load;
* QtWebEngine (map) can be imported.

Writes a JSON report (default ``%TEMP%\\osinthub_selftest.json``) and exits
with 0 when everything passed, 1 otherwise. Used by build.bat after packaging.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable


def _check(results: list[dict[str, Any]], name: str, fn: Callable[[], str]) -> None:
    try:
        detail = fn()
        results.append({"check": name, "ok": True, "detail": detail})
    except Exception as exc:
        results.append({"check": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc(limit=3)})


def run(report_path: str | None = None) -> int:
    os.environ.setdefault("OSINTHUB_DATA_DIR", tempfile.mkdtemp(prefix="osinthub-selftest-"))
    from .adapters.base import RunContext, registry
    from .config import Settings, tools_dir
    from .core import proc
    from .core.schema import TargetType

    settings = Settings(Path(os.environ["OSINTHUB_DATA_DIR"]) / "settings.json")
    results: list[dict[str, Any]] = []

    def adapters() -> str:
        names = list(registry())
        assert set(names) >= {"exiftool", "phoneinfoga", "holehe", "spiderfoot", "sherlock"}, names
        return ", ".join(names)

    _check(results, "adapters discovered", adapters)
    for name, cls in registry().items():
        a = cls(settings)

        def avail(a=a) -> str:
            ok, reason = a.availability()
            assert ok, reason
            return f"v{a.version()}"

        _check(results, f"{name} available", avail)

    def exif() -> str:
        from PySide6.QtGui import QColor, QImage

        img = QImage(64, 48, QImage.Format.Format_RGB32)
        img.fill(QColor("#243641"))
        path = Path(os.environ["OSINTHUB_DATA_DIR"]) / "selftest_фото.jpg"
        assert img.save(str(path), "JPEG")
        a = registry()["exiftool"](settings)
        argfile = path.with_suffix(".args")
        argfile.write_text("\n".join(["-charset", "filename=utf8", "-overwrite_original", "-GPSLatitude=55.7512",
                                      "-GPSLatitudeRef=N", "-GPSLongitude=37.6184", "-GPSLongitudeRef=E",
                                      "-Make=SelfTest", str(path)]) + "\n", encoding="utf-8")
        asyncio.run(proc.run([a.exe, "-@", str(argfile)], timeout=60))
        res = asyncio.run(a.execute(str(path), TargetType.FILE, RunContext("exiftool", str(path), TargetType.FILE, 60)))
        assert res.status == "done", res.error
        geo = [f.value for f in res.findings if f.type == "geo"]
        assert geo == ["55.751200, 37.618400"], geo
        return f"{len(res.findings)} findings, GPS {geo[0]}"

    _check(results, "exiftool extracts GPS", exif)

    def phoneinfoga() -> str:
        a = registry()["phoneinfoga"](settings)
        r = asyncio.run(proc.run([a.exe, "version"], timeout=30))
        assert r.returncode == 0 and "PhoneInfoga" in r.stdout, r.stdout + r.stderr
        return r.stdout.strip()

    _check(results, "phoneinfoga runs", phoneinfoga)

    def spiderfoot() -> str:
        a = registry()["spiderfoot"](settings)
        r = asyncio.run(proc.run([a.python, "-X", "utf8", a.sf_py, "-V"], timeout=60, env=a._env(),
                                 cwd=a.sf_py.parent))
        assert "SpiderFoot" in r.stdout + r.stderr, r.stdout + r.stderr
        return (r.stdout or r.stderr).strip().splitlines()[-1]

    _check(results, "spiderfoot runs", spiderfoot)

    def holehe() -> str:
        from .adapters.holehe import _load_modules

        n = len(_load_modules())
        assert n > 50, n
        return f"{n} modules"

    _check(results, "holehe modules load", holehe)

    def sherlock() -> str:
        a = registry()["sherlock"](settings)
        from .adapters.sherlock import _ensure_pandas_stub

        _ensure_pandas_stub()
        importlib.import_module("sherlock_project.sherlock")  # imports pandas/tomli at top level

        n = len(a._site_data())
        assert n > 100, n
        return f"{n} sites"

    _check(results, "sherlock site list loads", sherlock)

    def webengine() -> str:
        importlib.import_module("PySide6.QtWebEngineWidgets")
        return "QtWebEngineWidgets import ok"

    _check(results, "map engine import", webengine)

    ok = all(r["ok"] for r in results)
    report = {"ok": ok, "tools_dir": str(tools_dir()), "frozen": bool(getattr(sys, "frozen", False)),
              "results": results}
    out = Path(report_path or Path(tempfile.gettempdir()) / "osinthub_selftest.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1
