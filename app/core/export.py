"""Report export to JSON (machine-readable) and HTML (self-contained, printable)."""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import APP_TITLE, APP_VERSION, resource_dir
from .schema import TargetType, utcnow
from .storage import ScanRecord

TYPE_LABELS = {
    "account": "Аккаунт", "email": "Email", "phone": "Телефон", "username": "Никнейм",
    "domain": "Домен", "ip": "IP", "url": "Ссылка", "geo": "Геоданные", "location": "Место",
    "device": "Устройство", "datetime": "Дата", "author": "Автор", "software": "Программа",
    "carrier": "Оператор", "person": "Персона", "other": "Прочее",
}
CONFIDENCE_LABELS = {"high": "Высокая", "medium": "Средняя", "low": "Низкая"}
STATUS_LABELS = {"queued": "В очереди", "running": "Идёт", "done": "Готово", "error": "Ошибка",
                 "cancelled": "Остановлено"}


@dataclass(slots=True)
class ExportOptions:
    """Which report sections to include (matches the export dialog)."""

    summary: bool = True     # scan info and counts
    findings: bool = True    # findings table with sources
    metadata: bool = True    # raw tool output / metadata, related objects
    log: bool = False        # technical log


def build_report(scan: ScanRecord, opts: ExportOptions | None = None) -> dict[str, Any]:
    """Assemble the report as a plain dict (also the JSON export format)."""
    opts = opts or ExportOptions()
    findings = [{"tool": tool, **f.to_dict()} for tool, res in scan.results.items() for f in res.findings]
    report: dict[str, Any] = {
        "generator": f"{APP_TITLE} {APP_VERSION}",
        "generated_at": utcnow(),
        "scan": {
            "id": scan.id, "target": scan.target, "target_type": scan.target_type,
            "status": scan.status, "created_at": scan.created_at, "finished_at": scan.finished_at,
            "tools": scan.tools,
        },
    }
    if opts.summary:
        report["summary"] = {
            "total_findings": len(findings),
            "by_type": dict(Counter(f["type"] for f in findings).most_common()),
            "by_tool": {t: {"status": r.status, "findings": len(r.findings), "error": r.error,
                            "started_at": r.started_at, "finished_at": r.finished_at}
                        for t, r in scan.results.items()},
        }
    if opts.findings:
        report["findings"] = findings
    if opts.metadata:
        report["raw"] = {t: r.raw for t, r in scan.results.items()}
    if opts.log:
        report["log"] = {t: run.log for t, run in scan.runs.items()}
    return report


MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
              "октября", "ноября", "декабря"]


def human_dt(iso: str | None) -> str:
    """ISO-8601 (UTC) → local «1 октября 2026, 16:54»."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone()
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def display_target(target: str, target_type: str) -> str:
    if target_type == TargetType.USERNAME.value:
        return f"@{target}"
    if target_type == TargetType.FILE.value:
        return Path(target).name
    return target


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(resource_dir() / "app" / "core" / "templates")),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    env.filters["tojson_pretty"] = lambda v: json.dumps(v, ensure_ascii=False, indent=2, default=str)
    env.filters["dt"] = human_dt
    return env


def render_html(scan: ScanRecord, opts: ExportOptions | None = None) -> str:
    opts = opts or ExportOptions()
    report = build_report(scan, opts)
    geo = [f for f in report.get("findings", []) if f["type"] == "geo" and "lat" in f.get("extra", {})]
    raw_text = {t: json.dumps(r, ensure_ascii=False, indent=2, default=str)[:200_000]
                for t, r in report.get("raw", {}).items()}
    return _env().get_template("report.html.j2").render(
        r=report, opts=opts, geo=geo, raw_text=raw_text,
        type_label=lambda t: TYPE_LABELS.get(t, t),
        conf_label=lambda c: CONFIDENCE_LABELS.get(c, c),
        status_label=lambda s: STATUS_LABELS.get(s, s),
        target_label=TargetType(scan.target_type).label if scan.target_type in TargetType._value2member_map_ else scan.target_type,
        target_display=display_target(scan.target, scan.target_type),
    )


def export(scan: ScanRecord, path: str | Path, fmt: str, opts: ExportOptions | None = None) -> int:
    """Write the report to ``path`` (``fmt`` = ``json`` | ``html``). Returns the file size."""
    path = Path(path)
    if fmt == "json":
        text = json.dumps(build_report(scan, opts), ensure_ascii=False, indent=2, default=str)
    elif fmt == "html":
        text = render_html(scan, opts)
    else:
        raise ValueError(f"Неизвестный формат: {fmt}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path.stat().st_size
