"""Holehe adapter: which services an email address is registered on.

Holehe is used as a library inside the process: each of its modules is an
``async def module(email, client, out)`` coroutine using ``httpx``. We run
them on our own event loop with bounded concurrency, which gives per-module
progress and clean cancellation (no subprocess, no console window).

Holehe hasn't been updated since 2024, so individual modules may break or be
rate-limited by the target site; those are reported as "unchecked", never as
a failure of the whole tool.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
from typing import Any, Callable

from ..core.schema import Confidence, Finding, FindingType, TargetType
from .base import OptionSpec, RunContext, ToolAdapter, ToolError

# Modules that probe via the password-recovery flow. Excluded by default:
# they are the most likely to be noticed by the account owner.
PASSWORD_RECOVERY_MODULES = frozenset({"adobe", "mail_ru", "odnoklassniki", "samsung"})

_functions_cache: list[Callable[..., Any]] | None = None


def _load_modules() -> list[Callable[..., Any]]:
    global _functions_cache
    if _functions_cache is None:
        try:
            from holehe.core import get_functions, import_submodules
        except ImportError as exc:
            raise ToolError(f"Библиотека holehe не установлена: {exc}") from exc
        _functions_cache = get_functions(import_submodules("holehe.modules"))
    return _functions_cache


class HoleheAdapter(ToolAdapter):
    name = "holehe"
    title = "Holehe"
    description = "Регистрация email на сервисах"
    homepage = "https://github.com/megadose/holehe"
    input_types = frozenset({TargetType.EMAIL})
    default_timeout = 180
    icon = "at-sign"
    accent = "green"
    order = 30
    options = (
        OptionSpec("concurrency", "Параллельных запросов", "int", 20, minimum=1, maximum=64),
        OptionSpec("request_timeout", "Таймаут запроса, с", "int", 15, minimum=3, maximum=120),
        OptionSpec("password_recovery", "Модули через восстановление пароля", "bool", False,
                   "Adobe, Mail.ru, OK, Samsung — владелец может заметить проверку"),
    )

    def availability(self) -> tuple[bool, str]:
        try:
            importlib.metadata.version("holehe")
        except importlib.metadata.PackageNotFoundError:
            return False, "пакет holehe не найден"
        return True, ""

    def version(self) -> str | None:
        try:
            return importlib.metadata.version("holehe")
        except importlib.metadata.PackageNotFoundError:
            return None

    async def run(self, target: str, ctx: RunContext) -> Any:
        import httpx

        funcs = _load_modules()
        if not self.option("password_recovery"):
            funcs = [f for f in funcs if f.__name__ not in PASSWORD_RECOVERY_MODULES]
        total = len(funcs)
        out: list[dict[str, Any]] = []
        ctx.partial = {"results": out, "checked": total}
        sem = asyncio.Semaphore(int(self.option("concurrency")))
        done = 0

        async def one(fn: Callable[..., Any], client: httpx.AsyncClient) -> None:
            nonlocal done
            async with sem:
                ctx.check_cancelled()
                # Each module writes into its own list: modules run concurrently, so
                # slicing a shared list would attribute other modules' entries to this one.
                local: list[dict[str, Any]] = []
                try:
                    await fn(target, client, local)
                except Exception as exc:  # broken module / network error
                    local.append({"name": fn.__name__, "domain": fn.__name__, "exists": False,
                                  "rateLimit": False, "error": f"{type(exc).__name__}: {exc}"[:200]})
                out.extend(local)
                done += 1
                for entry in local:
                    if entry.get("exists"):
                        ctx.log(f"[FOUND] {entry.get('domain')}", "found")
                ctx.progress(done / total, f"Проверено {done} из {total}")

        timeout = httpx.Timeout(float(self.option("request_timeout")))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            ctx.log(f"Holehe: {total} модулей", "info")
            await asyncio.gather(*(one(f, client) for f in funcs))
        return {"results": out, "checked": total}

    def parse_output(self, raw: Any) -> list[Finding]:
        results: list[dict[str, Any]] = (raw or {}).get("results", []) if isinstance(raw, dict) else list(raw or [])
        findings: list[Finding] = []
        for r in sorted(results, key=lambda x: str(x.get("domain", ""))):
            if not r.get("exists"):
                continue
            domain = str(r.get("domain") or r.get("name") or "")
            conf = Confidence.MEDIUM if r.get("frequent_rate_limit") else Confidence.HIGH
            findings.append(Finding(FindingType.ACCOUNT.value, domain, "Holehe", conf.value,
                                    {"site": r.get("name", ""), "method": r.get("method", ""),
                                     "url": f"https://{domain}"}))
            if r.get("emailrecovery"):
                findings.append(Finding(FindingType.EMAIL.value, str(r["emailrecovery"]), f"Holehe · {domain}",
                                        Confidence.LOW.value, {"field": "Резервный email", "masked": True}))
            if r.get("phoneNumber"):
                findings.append(Finding(FindingType.PHONE.value, str(r["phoneNumber"]), f"Holehe · {domain}",
                                        Confidence.LOW.value, {"field": "Телефон восстановления", "masked": True}))
            others = r.get("others")
            if isinstance(others, dict):
                for k, v in others.items():
                    if v not in (None, ""):
                        findings.append(Finding(FindingType.OTHER.value, f"{k}: {v}", f"Holehe · {domain}",
                                                Confidence.MEDIUM.value, {"field": str(k)}))
        return findings

    @staticmethod
    def stats(raw: Any) -> dict[str, int]:
        """Counts for the UI: registered / not found / rate-limited or failed."""
        results = (raw or {}).get("results", []) if isinstance(raw, dict) else []
        return {
            "checked": len(results),
            "found": sum(1 for r in results if r.get("exists")),
            "unchecked": sum(1 for r in results if r.get("rateLimit") or r.get("error")),
        }
