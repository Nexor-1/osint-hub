"""PhoneInfoga adapter: carrier, region and web footprint of a phone number.

PhoneInfoga v2 has no JSON output for ``scan``; its REST mode (``serve``)
binds to *all* interfaces with no host option, which would trigger a Windows
Firewall prompt and expose an API on the LAN. We therefore run
``phoneinfoga scan`` and parse its (stable, reflection-generated) console
format: ``Results for <scanner>`` blocks of ``Key: value`` lines, list
sections ``Name:`` with tab-indented items separated by blank lines, and an
optional ``The following scanners returned errors:`` block.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import SecretSpec
from ..core import proc
from ..core.schema import Confidence, Finding, FindingType, TargetType
from .base import OptionSpec, RunContext, ToolAdapter, ToolError

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_RESULTS_RE = re.compile(r"^Results for (\S+)\s*$")
_SUCCEEDED_RE = re.compile(r"^(\d+) scanner\(s\) succeeded")
_KV_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 ]*?):(?: (.*))?$")

SCANNERS = ("local", "numverify", "googlesearch", "googlecse", "ovh")

SECTION_LABELS = {
    "Social media": "Соцсети",
    "Disposable providers": "Одноразовые номера",
    "Reputation": "Репутация",
    "Individuals": "Люди",
    "General": "Общий поиск",
    "Items": "Результаты поиска",
}


def parse_console(text: str) -> dict[str, Any]:
    """Parse PhoneInfoga console output into a dict.

    Returns ``{"scanners": {name: {"fields": {...}, "sections": {name: [item, ...]}}},
    "errors": {name: message}, "succeeded": int | None}``.
    """
    out: dict[str, Any] = {"scanners": {}, "errors": {}, "succeeded": None}
    scanner: dict[str, Any] | None = None
    section: list[dict[str, str]] | None = None
    item: dict[str, str] | None = None
    in_errors = False

    for raw_line in _ANSI_RE.sub("", text).splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            item = None  # blank line separates list items
            continue
        if m := _RESULTS_RE.match(line):
            scanner = {"fields": {}, "sections": {}}
            out["scanners"][m.group(1)] = scanner
            section = item = None
            in_errors = False
            continue
        if line.startswith("The following scanners returned errors"):
            in_errors, scanner, section = True, None, None
            continue
        if m := _SUCCEEDED_RE.match(line):
            out["succeeded"] = int(m.group(1))
            in_errors = False
            continue
        if in_errors:
            name, _, msg = line.partition(":")
            out["errors"][name.strip()] = msg.strip()
            continue
        if scanner is None:
            continue  # banner such as "Running scan for phone number ..."

        indented = line.startswith("\t")
        m = _KV_RE.match(line.strip())
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if indented and section is not None:
            if item is None:
                item = {}
                section.append(item)
            item[key] = value or ""
        elif value is None:
            section = scanner["sections"].setdefault(key, [])
            item = None
        else:
            scanner["fields"][key] = value
            section = item = None
    return out


class PhoneInfogaAdapter(ToolAdapter):
    name = "phoneinfoga"
    title = "PhoneInfoga"
    description = "Оператор, регион и упоминания"
    homepage = "https://github.com/sundowndev/phoneinfoga"
    input_types = frozenset({TargetType.PHONE})
    default_timeout = 120
    icon = "phone"
    accent = "gold"
    order = 20
    secrets = (
        SecretSpec("numverify_api_key", "Numverify API key", "NUMVERIFY_API_KEY",
                   "apilayer.com → Number Verification API"),
        SecretSpec("google_api_key", "Google API key (CSE)", "GOOGLE_API_KEY",
                   "Google Cloud → Custom Search JSON API"),
        SecretSpec("googlecse_cx", "Google CSE ID (cx)", "GOOGLECSE_CX",
                   "programmablesearchengine.google.com"),
    )
    options = (
        OptionSpec("scan_googlesearch", "Ссылки Google-дорков", "bool", True,
                   "Готовые поисковые запросы по соцсетям и сайтам одноразовых номеров"),
        OptionSpec("scan_ovh", "OVH Telecom", "bool", True, "Поиск номера в базе OVH (FR, BE, …)"),
        OptionSpec("scan_numverify", "Numverify", "bool", True, "Нужен API-ключ"),
        OptionSpec("scan_googlecse", "Google Custom Search", "bool", True, "Нужны API-ключ и CX"),
    )

    @property
    def exe(self) -> Path:
        return self.tools_dir / "phoneinfoga" / "phoneinfoga.exe"

    def availability(self) -> tuple[bool, str]:
        return (True, "") if self.exe.exists() else (False, f"нет файла {self.exe}")

    def version(self) -> str | None:
        f = self.exe.parent / "VERSION"
        return f.read_text(encoding="utf-8").strip() if f.exists() else None

    async def run(self, target: str, ctx: RunContext) -> Any:
        number = target.lstrip("+")  # PhoneInfoga wants digits only
        if not number.isdigit():
            raise ToolError("Номер должен состоять только из цифр")
        args: list[str] = [str(self.exe), "scan", "-n", number]
        for scanner in ("googlesearch", "ovh", "numverify", "googlecse"):
            if not self.option(f"scan_{scanner}"):
                args += ["-D", scanner]

        env = {
            "NO_COLOR": "1",
            "NUMVERIFY_API_KEY": self.secret("numverify_api_key"),
            "GOOGLE_API_KEY": self.secret("google_api_key"),
            "GOOGLECSE_CX": self.secret("googlecse_cx"),
        }
        seen: list[str] = []

        def on_line(line: str) -> None:
            if m := _RESULTS_RE.match(_ANSI_RE.sub("", line)):
                seen.append(m.group(1))
                ctx.log(f"[FOUND] PhoneInfoga: {m.group(1)}", "found")
                ctx.progress(min(0.95, len(seen) / len(SCANNERS)), f"Сканер {m.group(1)}")

        ctx.progress(0.05, "Запуск сканеров")
        res = await proc.run(args, timeout=ctx.timeout, cwd=self.work_dir, env=env,
                             on_stdout=on_line, on_stderr=lambda l: ctx.log(l, "warn"))
        parsed = parse_console(res.stdout)
        if res.returncode != 0 and not parsed["scanners"]:
            msg = (res.stderr or res.stdout).strip().splitlines()
            raise ToolError(f"PhoneInfoga завершился с кодом {res.returncode}: {msg[-1] if msg else ''}")
        for name, err in parsed["errors"].items():
            ctx.log(f"PhoneInfoga/{name}: {err}", "warn")
        parsed["stdout"] = res.stdout
        return parsed

    def parse_output(self, raw: Any) -> list[Finding]:
        if isinstance(raw, str):
            raw = parse_console(raw)
        scanners: dict[str, Any] = (raw or {}).get("scanners", {})
        out: list[Finding] = []

        local = scanners.get("local", {}).get("fields", {})
        if local.get("E164"):
            out.append(Finding(FindingType.PHONE.value, local["E164"], "PhoneInfoga · local",
                               Confidence.HIGH.value,
                               {"field": "E.164", "local": local.get("Local", "")}))
        if local.get("Country"):
            out.append(Finding(FindingType.LOCATION.value, local["Country"], "PhoneInfoga · local",
                               Confidence.HIGH.value, {"field": "Страна"}))
        if local.get("Carrier"):
            out.append(Finding(FindingType.CARRIER.value, local["Carrier"], "PhoneInfoga · local",
                               Confidence.MEDIUM.value, {"field": "Оператор (исходный)"}))

        nv = scanners.get("numverify", {}).get("fields", {})
        if nv.get("Valid", "").lower() == "true":
            if nv.get("Carrier"):
                out.append(Finding(FindingType.CARRIER.value, nv["Carrier"], "PhoneInfoga · Numverify",
                                   Confidence.HIGH.value, {"field": "Оператор", "line_type": nv.get("Line type", "")}))
            place = ", ".join(x for x in (nv.get("Location"), nv.get("Country name")) if x)
            if place:
                out.append(Finding(FindingType.LOCATION.value, place, "PhoneInfoga · Numverify",
                                   Confidence.MEDIUM.value, {"field": "Регион"}))
            if nv.get("Line type"):
                out.append(Finding(FindingType.OTHER.value, f"Тип линии: {nv['Line type']}",
                                   "PhoneInfoga · Numverify", Confidence.HIGH.value, {"field": "Тип линии"}))

        ovh = scanners.get("ovh", {}).get("fields", {})
        if ovh.get("Found", "").lower() == "true":
            place = " ".join(x for x in (ovh.get("Zip code"), ovh.get("City")) if x)
            out.append(Finding(FindingType.LOCATION.value, place or "найден в OVH Telecom", "PhoneInfoga · OVH",
                               Confidence.MEDIUM.value, {"field": "OVH", "range": ovh.get("Number range", "")}))

        cse = scanners.get("googlecse", {}).get("sections", {})
        for it in cse.get("Items", []):
            if it.get("URL"):
                out.append(Finding(FindingType.URL.value, it["URL"], "PhoneInfoga · Google CSE",
                                   Confidence.MEDIUM.value, {"title": it.get("Title", ""), "url": it["URL"],
                                                             "field": "Упоминание"}))

        gs = scanners.get("googlesearch", {}).get("sections", {})
        for section, items in gs.items():
            for it in items:
                if it.get("URL"):
                    out.append(Finding(FindingType.URL.value, it["URL"], "PhoneInfoga · Google dork",
                                       Confidence.LOW.value,
                                       {"url": it["URL"], "kind": "dork",
                                        "field": SECTION_LABELS.get(section, section)}))
        return out
