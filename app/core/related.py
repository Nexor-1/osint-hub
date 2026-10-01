"""Related findings: pivots that can be re-scanned with other tools in one click.

If one tool discovered an email, username, phone, domain or IP, we offer to
run it through the tools that accept that type. Masked values (``j***@x.com``
from Holehe recovery hints) are never offered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import validation
from .schema import FindingType, TargetType, ToolResult

_FINDING_TO_TARGET = {
    FindingType.USERNAME.value: TargetType.USERNAME,
    FindingType.EMAIL.value: TargetType.EMAIL,
    FindingType.PHONE.value: TargetType.PHONE,
    FindingType.DOMAIN.value: TargetType.DOMAIN,
    FindingType.IP.value: TargetType.IP,
}
_PRIORITY = [TargetType.USERNAME, TargetType.EMAIL, TargetType.PHONE, TargetType.DOMAIN, TargetType.IP]

# Big shared mail providers — their domain says nothing about the person.
_COMMON_MAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yandex.ru", "ya.ru", "mail.ru", "bk.ru", "list.ru", "inbox.ru",
    "outlook.com", "hotmail.com", "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me",
    "protonmail.com", "gmx.com", "gmx.de", "rambler.ru", "aol.com",
})


@dataclass(slots=True)
class Pivot:
    """A value worth scanning next."""

    value: str
    type: TargetType
    tools: list[str]
    sources: list[str] = field(default_factory=list)


def find_pivots(
    target: str,
    target_type: TargetType,
    results: Iterable[ToolResult],
    tools_for: dict[TargetType, list[str]],
    *,
    exclude: Iterable[str] = (),
    limit: int = 20,
    default_region: str | None = None,
) -> list[Pivot]:
    """Collect distinct, valid pivots from ``results``.

    ``tools_for`` maps a target type to the enabled tools that accept it.
    ``exclude`` contains values already scanned (e.g. parent scans).
    """
    seen = {target.strip().lower(), *(e.strip().lower() for e in exclude)}
    pivots: dict[tuple[TargetType, str], Pivot] = {}

    def add(raw_value: str, ttype: TargetType, source: str) -> None:
        if "*" in raw_value or "•" in raw_value:  # masked hint
            return
        try:
            value = validation.normalize(raw_value, ttype, default_region=default_region)
        except validation.ValidationError:
            return
        if value.lower() in seen or not tools_for.get(ttype):
            return
        if ttype is TargetType.DOMAIN and value in _COMMON_MAIL_DOMAINS:
            return
        key = (ttype, value.lower())
        if key not in pivots:
            pivots[key] = Pivot(value, ttype, list(tools_for[ttype]))
        if source not in pivots[key].sources:
            pivots[key].sources.append(source)

    # The local part of an email is a natural username candidate.
    if target_type is TargetType.EMAIL:
        add(target.split("@", 1)[0], TargetType.USERNAME, "часть email")

    for res in results:
        for f in res.findings:
            ttype = _FINDING_TO_TARGET.get(f.type)
            if ttype is None or f.extra.get("masked"):
                continue
            add(f.value, ttype, f.source or res.tool)

    ordered = sorted(pivots.values(), key=lambda p: (_PRIORITY.index(p.type), -len(p.sources), p.value))
    return ordered[:limit]
