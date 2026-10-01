"""Base class and registry for tool adapters.

To add a new tool, create ``app/adapters/<tool>.py`` with a subclass of
:class:`ToolAdapter` that sets ``name`` and implements :meth:`run` and
:meth:`parse_output`. It is discovered automatically and appears on the home
screen, in Settings and in exports — no other code needs to change.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar

from ..config import SecretSpec, Settings, data_dir, tools_dir
from ..core import validation
from ..core.proc import ToolNotFoundError
from ..core.schema import Finding, Status, TargetType, ToolResult, dedupe, utcnow

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type["ToolAdapter"]] = {}


class ToolError(RuntimeError):
    """An expected failure with a message that can be shown to the user as-is."""


@dataclass(frozen=True, slots=True)
class OptionSpec:
    """A user-editable, non-secret adapter option rendered on the Settings page."""

    key: str
    label: str
    kind: str  # "bool" | "int" | "str" | "choice"
    default: Any
    help: str = ""
    choices: tuple[tuple[str, str], ...] = ()  # (value, label) for "choice"
    minimum: int | None = None
    maximum: int | None = None


LogFn = Callable[[str, str], None]          # (level, message)
ProgressFn = Callable[[float | None, str], None]  # (fraction 0..1 or None, note)


@dataclass
class RunContext:
    """Per-run services handed to :meth:`ToolAdapter.run`.

    ``partial`` may be filled by the adapter while it runs; if the run times
    out, :meth:`ToolAdapter.parse_output` is applied to it so the user still
    sees what was collected before the deadline.
    """

    tool: str
    target: str
    target_type: TargetType
    timeout: float
    on_log: LogFn = lambda level, msg: None
    on_progress: ProgressFn = lambda frac, note: None
    cancelled: threading.Event = field(default_factory=threading.Event)
    partial: Any = None

    def log(self, msg: str, level: str = "info") -> None:
        self.on_log(level, msg)

    def progress(self, fraction: float | None, note: str = "") -> None:
        if fraction is not None:
            fraction = max(0.0, min(1.0, fraction))
        self.on_progress(fraction, note)

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError()


class ToolAdapter(ABC):
    """Uniform interface around one OSINT tool.

    Subclasses declare metadata as class attributes and implement
    :meth:`run` (collect raw output) and :meth:`parse_output` (pure function
    raw → findings, unit-tested against fixtures).
    """

    # --- metadata (override in subclasses) ---------------------------------
    name: ClassVar[str] = ""
    title: ClassVar[str] = ""
    description: ClassVar[str] = ""       # short, shown on the tool tile
    homepage: ClassVar[str] = ""
    input_types: ClassVar[frozenset[TargetType]] = frozenset()
    secrets: ClassVar[tuple[SecretSpec, ...]] = ()
    options: ClassVar[tuple[OptionSpec, ...]] = ()
    default_timeout: ClassVar[int] = 300
    icon: ClassVar[str] = "search"        # icon key in the UI icon set
    accent: ClassVar[str] = "violet"      # tile colour: violet|gold|green|pink|blue
    order: ClassVar[int] = 100            # position on the home screen

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
                raise RuntimeError(f"Duplicate adapter name: {cls.name}")
            _REGISTRY[cls.name] = cls

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # --- environment ----------------------------------------------------------
    @property
    def tools_dir(self) -> Path:
        return tools_dir()

    @property
    def work_dir(self) -> Path:
        """Writable per-tool directory under ``%APPDATA%\\OSINTHub``."""
        d = data_dir() / "work" / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def option(self, key: str) -> Any:
        spec = next((o for o in self.options if o.key == key), None)
        default = spec.default if spec else None
        return self.settings.tool_option(self.name, key, default)

    def secret(self, key: str) -> str:
        spec = next(s for s in self.secrets if s.key == key)
        return self.settings.secret(spec)

    def timeout(self) -> int:
        return int(self.settings.tool_option(self.name, "timeout", self.default_timeout))

    def availability(self) -> tuple[bool, str]:
        """``(True, "")`` if the tool can run, else ``(False, reason)``."""
        return True, ""

    def version(self) -> str | None:
        """Installed tool version, if known (cheap; no network)."""
        return None

    # --- the three-step contract --------------------------------------------
    def validate_input(self, target: str, target_type: TargetType) -> str:
        """Validate and normalise the target. Raise ``ValidationError`` if bad."""
        if target_type not in self.input_types:
            raise validation.ValidationError(f"{self.title} не работает с типом «{target_type.label}»")
        return validation.normalize(
            target,
            target_type,
            default_region=self.settings.get("default_region"),
            max_file_bytes=int(self.settings.get("max_file_mb", 100)) * 1_048_576,
        )

    @abstractmethod
    async def run(self, target: str, ctx: RunContext) -> Any:
        """Execute the tool and return JSON-serialisable raw output."""

    @abstractmethod
    def parse_output(self, raw: Any) -> list[Finding]:
        """Convert raw output into normalised findings. Must be side-effect free."""

    # --- orchestration ----------------------------------------------------------
    async def execute(self, target: str, target_type: TargetType, ctx: RunContext) -> ToolResult:
        """Validate → run (with timeout) → parse, converting every failure into
        a :class:`ToolResult` with a human-readable ``error``. Never raises
        except for programming errors in the caller."""
        result = ToolResult(tool=self.name, target=target, status=Status.RUNNING.value,
                            started_at=utcnow(), target_type=target_type.value)
        try:
            ok, reason = self.availability()
            if not ok:
                raise ToolError(f"{self.title} не установлен: {reason}")
            norm = self.validate_input(target, target_type)
            ctx.log(f"{self.title} запущен для {norm}", "run")
            raw = await asyncio.wait_for(self.run(norm, ctx), timeout=ctx.timeout)
            result.raw = raw
            result.findings = dedupe(self.parse_output(raw))
            result.status = Status.DONE.value
            ctx.log(f"{self.title}: готово, находок — {len(result.findings)}", "done")
        except validation.ValidationError as exc:
            self._fail(result, ctx, f"Некорректный ввод: {exc}")
        except (asyncio.TimeoutError, TimeoutError):
            ctx.cancelled.set()
            self._fail(result, ctx, f"Превышен таймаут {int(ctx.timeout)} с")
            self._salvage(result, ctx)
        except asyncio.CancelledError:
            ctx.cancelled.set()
            result.status = Status.CANCELLED.value
            result.error = "Остановлено пользователем"
            ctx.log(f"{self.title}: остановлен", "warn")
            self._salvage(result, ctx)
        except ToolNotFoundError as exc:
            self._fail(result, ctx, f"Не найден исполняемый файл: {exc}")
        except ToolError as exc:
            self._fail(result, ctx, str(exc))
        except Exception as exc:  # the tool itself crashed
            log.error("%s crashed:\n%s", self.name, traceback.format_exc())
            self._fail(result, ctx, f"Инструмент завершился с ошибкой: {type(exc).__name__}: {exc}")
            self._salvage(result, ctx)
        result.finished_at = utcnow()
        return result

    def _fail(self, result: ToolResult, ctx: RunContext, message: str) -> None:
        result.status = Status.ERROR.value
        result.error = message
        ctx.log(f"{self.title}: {message}", "error")

    def _salvage(self, result: ToolResult, ctx: RunContext) -> None:
        """Keep whatever was collected before a timeout / cancel / crash."""
        if ctx.partial is None or result.findings:
            return
        try:
            result.raw = ctx.partial
            result.findings = dedupe(self.parse_output(ctx.partial))
            if result.findings:
                ctx.log(f"{self.title}: сохранены частичные результаты ({len(result.findings)})", "warn")
        except Exception:
            log.debug("salvage failed for %s", self.name, exc_info=True)


def registry() -> dict[str, type[ToolAdapter]]:
    """All discovered adapters, sorted by ``order``."""
    from . import discover

    discover()
    return dict(sorted(_REGISTRY.items(), key=lambda kv: (kv[1].order, kv[0])))
