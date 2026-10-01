"""Sherlock adapter: find a username across ~400 sites and social networks.

Sherlock is used as a library: :func:`sherlock_project.sherlock.sherlock`
runs in a worker thread and reports every checked site through our
``QueryNotify`` subclass, which drives live progress, collects partial
results and aborts promptly on cancel/timeout.

Site database: by default the copy bundled with the package (works offline);
"Обновить базу сайтов" in Settings downloads the latest one into
``%APPDATA%\\OSINTHub\\sherlock\\data.json``, which then takes precedence.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from ..config import data_dir
from ..core.schema import Confidence, Finding, FindingType, TargetType
from .base import OptionSpec, RunContext, ToolAdapter, ToolError

_PROXY_RE = re.compile(r"^(?:https?|socks4a?|socks5h?)://[A-Za-z0-9._~%:@\-\[\]]+$")


class _Aborted(Exception):
    pass


def _ensure_pandas_stub() -> None:
    """sherlock.py imports pandas at module level but only uses it for its own
    xlsx export, which we never call. The packaged app excludes pandas/numpy
    (~60 MB); provide an empty module so the import succeeds."""
    import importlib.util
    import sys
    import types

    if "pandas" not in sys.modules and importlib.util.find_spec("pandas") is None:
        sys.modules["pandas"] = types.ModuleType("pandas")


def user_data_file() -> Path:
    return data_dir() / "sherlock" / "data.json"


def bundled_data_file() -> Path | None:
    try:
        import sherlock_project
    except ImportError:
        return None
    p = Path(sherlock_project.__file__).parent / "resources" / "data.json"
    return p if p.exists() else None


def update_site_data(timeout: float = 30) -> int:
    """Download the latest Sherlock site list. Returns the number of sites."""
    from sherlock_project.sites import MANIFEST_URL

    req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "OSINTHub"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    data = json.loads(payload)
    if not isinstance(data, dict) or len(data) < 50:
        raise ToolError("Получена некорректная база сайтов Sherlock")
    dest = user_data_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, dest)
    return len([k for k in data if not k.startswith("$")])


class SherlockAdapter(ToolAdapter):
    name = "sherlock"
    title = "Sherlock"
    description = "Профили по никнейму на сайтах"
    homepage = "https://github.com/sherlock-project/sherlock"
    input_types = frozenset({TargetType.USERNAME})
    default_timeout = 300
    icon = "user-search"
    accent = "violet"
    order = 50
    options = (
        OptionSpec("request_timeout", "Таймаут запроса к сайту, с", "int", 30, minimum=5, maximum=120),
        OptionSpec("nsfw", "Включать NSFW-сайты", "bool", False),
        OptionSpec("proxy", "Прокси", "str", "", "Например socks5://127.0.0.1:9050 (пусто — без прокси)"),
    )

    def availability(self) -> tuple[bool, str]:
        try:
            importlib.metadata.version("sherlock-project")
        except importlib.metadata.PackageNotFoundError:
            return False, "пакет sherlock-project не найден"
        try:
            importlib.import_module("sherlock_project")
        except Exception as exc:  # broken install / missing dependency
            return False, f"не удалось загрузить sherlock_project: {exc}"
        if not (user_data_file().exists() or bundled_data_file()):
            return False, "нет базы сайтов data.json"
        return True, ""

    def version(self) -> str | None:
        try:
            return importlib.metadata.version("sherlock-project")
        except importlib.metadata.PackageNotFoundError:
            return None

    def _site_data(self) -> dict[str, dict[str, Any]]:
        from sherlock_project.sites import SitesInformation

        path = user_data_file() if user_data_file().exists() else bundled_data_file()
        try:
            sites = SitesInformation(data_file_path=str(path), honor_exclusions=False)
        except Exception as exc:
            raise ToolError(f"Не удалось загрузить базу сайтов Sherlock: {exc}") from exc
        if not self.option("nsfw"):
            sites.remove_nsfw_sites()
        return {site.name: site.information for site in sites}

    async def run(self, target: str, ctx: RunContext) -> Any:
        _ensure_pandas_stub()
        from sherlock_project.notify import QueryNotify
        from sherlock_project.result import QueryStatus
        from sherlock_project.sherlock import sherlock

        proxy = (self.option("proxy") or "").strip() or None
        if proxy and not _PROXY_RE.match(proxy):
            raise ToolError("Некорректный адрес прокси в настройках Sherlock")

        site_data = self._site_data()
        total = len(site_data)
        claimed: list[dict[str, Any]] = []
        ctx.partial = {"username": target, "total": total, "sites": claimed}
        ctx.log(f"Sherlock: проверка {total} сайтов", "info")

        class Notify(QueryNotify):
            checked = 0

            def update(self, result: Any) -> None:  # called once per site
                if ctx.cancelled.is_set():
                    raise _Aborted()
                Notify.checked += 1
                if result.status == QueryStatus.CLAIMED:
                    claimed.append({"site": result.site_name, "url_user": result.site_url_user,
                                    "status": "Claimed",
                                    "error_type": site_data.get(result.site_name, {}).get("errorType", "")})
                    ctx.log(f"[FOUND] {result.site_name}: {result.site_url_user}", "found")
                ctx.progress(Notify.checked / total, f"Проверено {Notify.checked} из {total}")

            def finish(self, message: Any = None) -> None:
                return None

        def work() -> dict[str, Any]:
            try:
                return sherlock(target, site_data, Notify(), proxy=proxy,
                                timeout=int(self.option("request_timeout")))
            except _Aborted:
                return {}

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, work)
        if ctx.cancelled.is_set():
            raise asyncio.CancelledError()

        sites: list[dict[str, Any]] = []
        for site, info in results.items():
            status = info.get("status")
            sites.append({
                "site": site,
                "url_main": info.get("url_main", ""),
                "url_user": info.get("url_user", ""),
                "status": str(getattr(status, "status", status) or ""),
                "http_status": info.get("http_status") if isinstance(info.get("http_status"), int) else None,
                "error_type": site_data.get(site, {}).get("errorType", ""),
                "context": str(getattr(status, "context", "") or "")[:200],
            })
        return {"username": target, "total": total, "sites": sites}

    def parse_output(self, raw: Any) -> list[Finding]:
        findings: list[Finding] = []
        for s in (raw or {}).get("sites", []):
            if s.get("status") != "Claimed" or not s.get("url_user"):
                continue
            etype = s.get("error_type")
            if isinstance(etype, list):
                etype = etype[0] if etype else ""
            # "status_code" detection is the most prone to false positives.
            conf = Confidence.MEDIUM if etype == "status_code" else Confidence.HIGH
            findings.append(Finding(FindingType.ACCOUNT.value, s["url_user"], s["site"], conf.value,
                                    {"site": s["site"], "url": s["url_user"],
                                     "username": (raw or {}).get("username", "")}))
        return findings
