"""Strict validation and normalisation of user-supplied targets.

Everything typed by the user (or found by a tool and re-submitted) passes
through :func:`normalize` before it reaches an adapter. Validators are
allow-list based: anything not matching the expected shape is rejected, and
no value may start with ``-`` so it can never be parsed as a CLI option.
"""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path

import phonenumbers

from .schema import TargetType


class ValidationError(ValueError):
    """Raised when a target does not match the expected format."""


MAX_TARGET_LEN = 254

_EMAIL_RE = re.compile(
    r"^(?=.{3,254}$)[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.\-]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Цель должна быть строкой")
    value = value.strip()
    if not value:
        raise ValidationError("Пустой ввод")
    if len(value) > MAX_TARGET_LEN:
        raise ValidationError(f"Слишком длинное значение (>{MAX_TARGET_LEN} символов)")
    if _CONTROL_RE.search(value):
        raise ValidationError("Недопустимые управляющие символы")
    if value.startswith("-"):
        raise ValidationError("Значение не может начинаться с «-»")
    return value


def normalize_email(value: str) -> str:
    value = _clean(value)
    if not _EMAIL_RE.match(value):
        raise ValidationError("Некорректный email")
    local, _, domain = value.rpartition("@")
    return f"{local}@{domain.lower()}"


def normalize_domain(value: str) -> str:
    value = _clean(value).lower().rstrip(".")
    value = re.sub(r"^https?://", "", value).split("/", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    try:
        ascii_domain = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValidationError("Некорректный домен") from exc
    labels = ascii_domain.split(".")
    if len(labels) < 2 or len(ascii_domain) > 253:
        raise ValidationError("Некорректный домен")
    if not all(_LABEL_RE.match(lbl) for lbl in labels) or not _TLD_RE.match(labels[-1]):
        raise ValidationError("Некорректный домен")
    return ascii_domain


def normalize_ip(value: str) -> str:
    value = _clean(value)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValidationError("Некорректный IP-адрес") from exc


def normalize_phone(value: str, default_region: str | None = None) -> str:
    """Return the number in E.164 form (``+79001234567``)."""
    value = _clean(value)
    if not re.fullmatch(r"[+\d\s().\-]{5,32}", value):
        raise ValidationError("Номер может содержать только цифры, пробелы, «+», «-», скобки")
    try:
        num = phonenumbers.parse(value, None if value.startswith("+") else (default_region or "RU"))
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("Не удалось разобрать номер телефона") from exc
    if not phonenumbers.is_possible_number(num):
        raise ValidationError("Номер телефона невозможной длины")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def normalize_username(value: str) -> str:
    value = _clean(value).lstrip("@")
    if not _USERNAME_RE.match(value):
        raise ValidationError("Никнейм: латиница, цифры, «_», «.», «-», до 64 символов")
    return value


def normalize_file(value: str, max_bytes: int | None = None) -> str:
    """Validate a local file path; returns the absolute path."""
    if not isinstance(value, (str, os.PathLike)):
        raise ValidationError("Некорректный путь")
    path = Path(value).expanduser()
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationError("Файл не найден") from exc
    if not path.is_file():
        raise ValidationError("Это не файл")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ValidationError(f"Файл больше {max_bytes // 1_048_576} МБ")
    return str(path)


def normalize(value: str, target_type: TargetType, *, default_region: str | None = None,
              max_file_bytes: int | None = None) -> str:
    """Dispatch to the validator for ``target_type``."""
    if target_type is TargetType.EMAIL:
        return normalize_email(value)
    if target_type is TargetType.DOMAIN:
        return normalize_domain(value)
    if target_type is TargetType.IP:
        return normalize_ip(value)
    if target_type is TargetType.PHONE:
        return normalize_phone(value, default_region)
    if target_type is TargetType.USERNAME:
        return normalize_username(value)
    if target_type is TargetType.FILE:
        return normalize_file(value, max_file_bytes)
    raise ValidationError(f"Неизвестный тип цели: {target_type}")
