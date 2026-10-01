"""ExifTool adapter: metadata (GPS, dates, device, author) from photos and documents.

Runs the bundled ``tools/exiftool/exiftool.exe``. All arguments, including
the file path, go through a UTF-8 ``-@`` argument file: on Windows Perl
receives command-line arguments in the ANSI code page, so a path with
Cyrillic characters would otherwise be mangled.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from ..core import proc
from ..core.schema import Confidence, Finding, FindingType, TargetType
from .base import RunContext, ToolAdapter, ToolError

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EXIF_DATE_RE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})")

# tag name (without group) -> (section, finding type, Russian label)
TAG_MAP: dict[str, tuple[str, FindingType, str]] = {
    # device
    "Make": ("device", FindingType.DEVICE, "Производитель"),
    "Model": ("device", FindingType.DEVICE, "Модель"),
    "LensModel": ("device", FindingType.DEVICE, "Объектив"),
    "LensID": ("device", FindingType.DEVICE, "Объектив"),
    "LensMake": ("device", FindingType.DEVICE, "Производитель объектива"),
    "SerialNumber": ("device", FindingType.DEVICE, "Серийный номер"),
    "BodySerialNumber": ("device", FindingType.DEVICE, "Серийный номер корпуса"),
    "InternalSerialNumber": ("device", FindingType.DEVICE, "Внутренний серийный номер"),
    "CameraSerialNumber": ("device", FindingType.DEVICE, "Серийный номер камеры"),
    "LensSerialNumber": ("device", FindingType.DEVICE, "Серийный номер объектива"),
    "HostComputer": ("device", FindingType.DEVICE, "Компьютер"),
    # date / time
    "DateTimeOriginal": ("datetime", FindingType.DATETIME, "Снято"),
    "CreateDate": ("datetime", FindingType.DATETIME, "Создано"),
    "ModifyDate": ("datetime", FindingType.DATETIME, "Изменено"),
    "MetadataDate": ("datetime", FindingType.DATETIME, "Метаданные изменены"),
    "GPSDateTime": ("datetime", FindingType.DATETIME, "Время GPS"),
    "OffsetTimeOriginal": ("datetime", FindingType.DATETIME, "Часовой пояс"),
    "OffsetTime": ("datetime", FindingType.DATETIME, "Часовой пояс"),
    # author
    "Artist": ("author", FindingType.AUTHOR, "Автор"),
    "Author": ("author", FindingType.AUTHOR, "Автор"),
    "Creator": ("author", FindingType.AUTHOR, "Создатель"),
    "XPAuthor": ("author", FindingType.AUTHOR, "Автор"),
    "By-line": ("author", FindingType.AUTHOR, "Автор"),
    "OwnerName": ("author", FindingType.AUTHOR, "Владелец"),
    "CameraOwnerName": ("author", FindingType.AUTHOR, "Владелец камеры"),
    "LastModifiedBy": ("author", FindingType.AUTHOR, "Изменил"),
    "Company": ("author", FindingType.AUTHOR, "Организация"),
    "Manager": ("author", FindingType.AUTHOR, "Руководитель"),
    "Copyright": ("author", FindingType.AUTHOR, "Авторские права"),
    "Rights": ("author", FindingType.AUTHOR, "Права"),
    # software
    "Software": ("author", FindingType.SOFTWARE, "Программа"),
    "CreatorTool": ("author", FindingType.SOFTWARE, "Программа"),
    "Producer": ("author", FindingType.SOFTWARE, "PDF-генератор"),
    "Application": ("author", FindingType.SOFTWARE, "Приложение"),
    "AppVersion": ("author", FindingType.SOFTWARE, "Версия приложения"),
    "HistorySoftwareAgent": ("author", FindingType.SOFTWARE, "История правок"),
    "XMPToolkit": ("author", FindingType.SOFTWARE, "XMP Toolkit"),
    # textual location
    "City": ("location", FindingType.LOCATION, "Город"),
    "State": ("location", FindingType.LOCATION, "Регион"),
    "Province-State": ("location", FindingType.LOCATION, "Регион"),
    "Country": ("location", FindingType.LOCATION, "Страна"),
    "Country-PrimaryLocationName": ("location", FindingType.LOCATION, "Страна"),
    "Sub-location": ("location", FindingType.LOCATION, "Место"),
    "Location": ("location", FindingType.LOCATION, "Место"),
}

# Groups whose values describe the local copy of the file, not its origin.
_SKIP_GROUPS = {"System", "ExifTool"}


def _split(key: str) -> tuple[str, str]:
    group, _, tag = key.rpartition(":")
    return group, tag


def _fmt_date(value: str) -> str:
    return _EXIF_DATE_RE.sub(r"\1-\2-\3", value)


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip().split()[0])
    except (ValueError, IndexError):
        return None


def extract_gps(meta: dict[str, Any]) -> dict[str, float] | None:
    """Signed decimal lat/lon (and altitude if present) from ExifTool JSON."""
    lat = _as_float(meta.get("Composite:GPSLatitude"))
    lon = _as_float(meta.get("Composite:GPSLongitude"))
    if lat is None or lon is None:
        # No composite tags (e.g. XMP-only) — combine value with its Ref.
        for key, val in meta.items():
            g, t = _split(key)
            if t == "GPSLatitude" and lat is None:
                lat = _as_float(val)
                ref = str(meta.get(f"{g}:GPSLatitudeRef", ""))
                if lat is not None and ref.upper().startswith("S"):
                    lat = -abs(lat)
            elif t == "GPSLongitude" and lon is None:
                lon = _as_float(val)
                ref = str(meta.get(f"{g}:GPSLongitudeRef", ""))
                if lon is not None and ref.upper().startswith("W"):
                    lon = -abs(lon)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:  # common "empty" placeholder written by some apps
        return None
    out = {"lat": round(lat, 6), "lon": round(lon, 6)}
    alt_raw = meta.get("Composite:GPSAltitude") or meta.get("GPS:GPSAltitude")
    alt = _as_float(alt_raw)
    if alt is not None:
        if "below" in str(alt_raw).lower():
            alt = -alt
        out["alt"] = alt
    return out


class ExifToolAdapter(ToolAdapter):
    name = "exiftool"
    title = "ExifTool"
    description = "Метаданные фото и документов"
    homepage = "https://exiftool.org"
    input_types = frozenset({TargetType.FILE})
    default_timeout = 60
    icon = "file-image"
    accent = "blue"
    order = 10

    @property
    def exe(self) -> Path:
        return self.tools_dir / "exiftool" / "exiftool.exe"

    def availability(self) -> tuple[bool, str]:
        if not self.exe.exists():
            return False, f"нет файла {self.exe}"
        if not (self.exe.parent / "exiftool_files").is_dir():
            return False, "нет папки exiftool_files рядом с exiftool.exe"
        return True, ""

    def version(self) -> str | None:
        f = self.exe.parent / "VERSION"
        return f.read_text(encoding="utf-8").strip() if f.exists() else None

    async def run(self, target: str, ctx: RunContext) -> Any:
        args = ["-charset", "filename=utf8", "-j", "-G1", "-a", "-s",
                "-c", "%+.6f", "-api", "largefilesupport=1", target]
        fd, argfile = tempfile.mkstemp(suffix=".args", dir=self.work_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(args) + "\n")
            ctx.progress(0.2, "Чтение метаданных")
            res = await proc.run([self.exe, "-@", argfile], timeout=ctx.timeout,
                                 on_stderr=lambda line: ctx.log(line, "warn"))
        finally:
            try:
                os.unlink(argfile)
            except OSError:
                pass
        if not res.stdout.strip():
            raise ToolError(f"ExifTool не вернул данных (код {res.returncode}): {res.stderr.strip()[:300]}")
        try:
            data = json.loads(res.stdout)
        except ValueError as exc:
            raise ToolError(f"Не удалось разобрать вывод ExifTool: {exc}") from exc
        ctx.progress(1.0, "Готово")
        meta = data[0] if isinstance(data, list) and data else {}
        return {"file": target, "metadata": meta}

    def parse_output(self, raw: Any) -> list[Finding]:
        meta: dict[str, Any] = (raw or {}).get("metadata") or {}
        findings: list[Finding] = []

        gps = extract_gps(meta)
        if gps:
            findings.append(Finding(
                type=FindingType.GEO.value,
                value=f"{gps['lat']:.6f}, {gps['lon']:.6f}",
                source="ExifTool",
                confidence=Confidence.HIGH.value,
                extra={"section": "location", "field": "Координаты", **gps},
            ))
            if "alt" in gps:
                findings.append(Finding(FindingType.LOCATION.value, f"{gps['alt']:g} м", "ExifTool",
                                        Confidence.HIGH.value,
                                        {"section": "location", "field": "Высота", "tag": "GPSAltitude"}))

        seen_values: set[tuple[str, str]] = set()
        for key, value in meta.items():
            group, tag = _split(key)
            if group in _SKIP_GROUPS or tag not in TAG_MAP or value in (None, ""):
                continue
            section, ftype, label = TAG_MAP[tag]
            text = ", ".join(map(str, value)) if isinstance(value, list) else str(value).strip()
            if ftype is FindingType.DATETIME:
                text = _fmt_date(text)
            if not text or (section, text.lower()) in seen_values:
                continue
            seen_values.add((section, text.lower()))
            findings.append(Finding(ftype.value, text, "ExifTool", Confidence.HIGH.value,
                                    {"section": section, "field": label, "tag": key}))

        # Emails hidden anywhere in metadata are useful pivots.
        for key, value in meta.items():
            if _split(key)[0] in _SKIP_GROUPS or not isinstance(value, str):
                continue
            for email in _EMAIL_RE.findall(value):
                findings.append(Finding(FindingType.EMAIL.value, email, "ExifTool", Confidence.MEDIUM.value,
                                        {"section": "author", "field": "Email в метаданных", "tag": key}))
        return findings

    @staticmethod
    def file_summary(raw: Any) -> dict[str, Any]:
        """File name/type/size/dimensions for the preview card."""
        meta = (raw or {}).get("metadata") or {}
        return {
            "name": meta.get("System:FileName") or Path((raw or {}).get("file", "")).name,
            "type": meta.get("File:FileType", ""),
            "size": meta.get("System:FileSize", ""),
            "dimensions": meta.get("Composite:ImageSize", ""),
            "mime": meta.get("File:MIMEType", ""),
        }
