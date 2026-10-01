"""Common result schema shared by every tool adapter.

Every adapter converts its native output into a :class:`ToolResult`::

    {tool, target, status, started_at, finished_at,
     findings: [{type, value, source, confidence}], raw}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TargetType(str, Enum):
    """Kinds of scan targets the app understands."""

    EMAIL = "email"
    PHONE = "phone"
    USERNAME = "username"
    DOMAIN = "domain"
    IP = "ip"
    FILE = "file"

    @property
    def label(self) -> str:
        return _TARGET_LABELS[self]


_TARGET_LABELS = {
    TargetType.EMAIL: "Email",
    TargetType.PHONE: "Телефон",
    TargetType.USERNAME: "Никнейм",
    TargetType.DOMAIN: "Домен",
    TargetType.IP: "IP",
    TargetType.FILE: "Файл",
}


class Status(str, Enum):
    """Lifecycle of a single tool run (and of a whole scan)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def is_final(self) -> bool:
        return self in (Status.DONE, Status.ERROR, Status.CANCELLED)


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingType(str, Enum):
    """Normalised categories of findings. ``value`` semantics depend on type."""

    ACCOUNT = "account"      # registered account / profile (value = URL or site)
    EMAIL = "email"
    PHONE = "phone"
    USERNAME = "username"
    DOMAIN = "domain"
    IP = "ip"
    URL = "url"
    GEO = "geo"              # value = "lat, lon"; extra: lat, lon, alt
    LOCATION = "location"    # textual location / address / region
    DEVICE = "device"
    DATETIME = "datetime"
    AUTHOR = "author"
    SOFTWARE = "software"
    CARRIER = "carrier"
    PERSON = "person"
    OTHER = "other"


def utcnow() -> str:
    """Current UTC time as ISO-8601 string with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class Finding:
    """One normalised piece of evidence produced by a tool.

    ``extra`` carries optional structured details (e.g. ``url``, ``field``,
    ``lat``/``lon``) that UI views may use; it is exported with the finding.
    """

    type: str
    value: str
    source: str
    confidence: str = Confidence.MEDIUM.value
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        return cls(
            type=str(d.get("type", FindingType.OTHER.value)),
            value=str(d.get("value", "")),
            source=str(d.get("source", "")),
            confidence=str(d.get("confidence", Confidence.MEDIUM.value)),
            extra=dict(d.get("extra") or {}),
        )

    def key(self) -> tuple[str, str]:
        """Identity used for de-duplication."""
        return (self.type, self.value.strip().lower())


@dataclass(slots=True)
class ToolResult:
    """Normalised outcome of one tool run on one target."""

    tool: str
    target: str
    status: str = Status.QUEUED.value
    started_at: str | None = None
    finished_at: str | None = None
    findings: list[Finding] = field(default_factory=list)
    raw: Any = None
    error: str | None = None
    target_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["findings"] = [f.to_dict() for f in self.findings]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolResult":
        return cls(
            tool=d["tool"],
            target=d["target"],
            status=d.get("status", Status.QUEUED.value),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            raw=d.get("raw"),
            error=d.get("error"),
            target_type=d.get("target_type"),
        )


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Remove duplicate findings, keeping the first (highest priority) one."""
    seen: set[tuple[str, str]] = set()
    out: list[Finding] = []
    for f in findings:
        k = f.key()
        if k in seen or not f.value.strip():
            continue
        seen.add(k)
        out.append(f)
    return out
