"""Guess the type of a free-form target typed into the main search box."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import validation as v
from .schema import TargetType


@dataclass(slots=True)
class Detection:
    """Result of type detection.

    ``type`` is the best guess (``None`` if nothing matched), ``value`` the
    normalised target and ``alternatives`` other plausible interpretations
    the UI may offer (e.g. ``john.doe`` is both a domain and a username).
    """

    type: TargetType | None
    value: str
    alternatives: list[TargetType] = field(default_factory=list)
    error: str | None = None


_PHONE_HINT = re.compile(r"^\+?[\d\s().\-]{6,32}$")


def detect(text: str, default_region: str | None = None) -> Detection:
    """Detect the target type of ``text``.

    Order matters: file path → email → IP → phone → domain → username.
    """
    raw = (text or "").strip().strip('"')
    if not raw:
        return Detection(None, "", error="Пустой ввод")

    if (len(raw) > 3 and raw[1:3] in (":\\", ":/")) or raw.startswith("\\\\"):
        if os.path.isfile(raw):
            return Detection(TargetType.FILE, raw)

    candidates: list[tuple[TargetType, str]] = []
    checks = [
        (TargetType.EMAIL, lambda s: v.normalize_email(s)),
        (TargetType.IP, lambda s: v.normalize_ip(s)),
        (TargetType.PHONE, lambda s: _phone(s, default_region)),
        (TargetType.DOMAIN, lambda s: v.normalize_domain(s)),
        (TargetType.USERNAME, lambda s: v.normalize_username(s)),
    ]
    for ttype, fn in checks:
        try:
            candidates.append((ttype, fn(raw)))
        except v.ValidationError:
            continue

    if not candidates:
        return Detection(None, raw, error="Не удалось определить тип: email, телефон, никнейм, домен или IP")

    best_type, best_value = candidates[0]
    # "@nick" is an explicit username even though it isn't anything else.
    if raw.startswith("@") and any(t is TargetType.USERNAME for t, _ in candidates):
        best_type, best_value = next((t, val) for t, val in candidates if t is TargetType.USERNAME)
    alternatives = [t for t, _ in candidates if t is not best_type]
    return Detection(best_type, best_value, alternatives)


def _phone(s: str, region: str | None) -> str:
    # Only treat as phone if it *looks* like one: starts with + or has ≥7 digits
    # and nothing but phone punctuation. Prevents "2024" becoming a phone.
    digits = sum(c.isdigit() for c in s)
    if not _PHONE_HINT.match(s) or digits < 7:
        raise v.ValidationError("not a phone")
    if not s.startswith("+") and digits < 10:
        raise v.ValidationError("ambiguous local number")
    return v.normalize_phone(s, region)
