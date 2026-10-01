"""Background scan engine.

All tool runs execute on a dedicated asyncio event loop in its own thread
(Windows Proactor loop, which supports subprocesses). The UI thread only
calls the thread-safe public methods and receives :class:`EngineEvent`
objects through a listener callback — the GUI never blocks on a scan.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..adapters.base import RunContext, ToolAdapter, registry
from ..config import Settings
from .schema import Status, TargetType, ToolResult, utcnow
from .storage import Storage

log = logging.getLogger(__name__)

MAX_LOG_LINES = 3000
PROGRESS_INTERVAL = 0.1  # seconds between progress events per run


@dataclass(slots=True)
class EngineEvent:
    """Notification sent to the UI.

    ``kind`` is one of ``scan_started``, ``run_status``, ``progress``, ``log``,
    ``scan_finished``. ``data`` depends on the kind (see ``ScanEngine``).
    """

    kind: str
    scan_id: int
    tool: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


Listener = Callable[[EngineEvent], None]


@dataclass
class _Run:
    ctx: RunContext
    task: asyncio.Task | None = None
    lines: list[str] = field(default_factory=list)
    last_progress: float = 0.0


class ScanEngine:
    """Queues scans, runs tool adapters concurrently and persists results."""

    def __init__(self, settings: Settings, storage: Storage, listener: Listener | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self._listeners: list[Listener] = [listener] if listener else []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_main, name="ScanEngine", daemon=True)
        self._runs: dict[tuple[int, str], _Run] = {}
        self._sem: asyncio.Semaphore | None = None
        self._started = threading.Event()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.storage.recover_interrupted()
        self._thread.start()
        self._started.wait(5)

    def _loop_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._sem = asyncio.Semaphore(max(1, int(self.settings.get("max_parallel_tools", 3))))
        self._started.set()
        self._loop.run_forever()

    def stop(self, timeout: float = 10) -> None:
        """Cancel everything (killing child processes) and stop the loop."""
        if not self._thread.is_alive():
            return
        for run in list(self._runs.values()):
            run.ctx.cancelled.set()
        fut = asyncio.run_coroutine_threadsafe(self._cancel_all(), self._loop)
        try:
            fut.result(timeout)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)

    async def _cancel_all(self) -> None:
        tasks = [r.task for r in self._runs.values() if r.task and not r.task.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=8)

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _emit(self, ev: EngineEvent) -> None:
        for fn in self._listeners:
            try:
                fn(ev)
            except Exception:
                log.exception("listener failed")

    # ------------------------------------------------------------ adapters
    def adapter(self, name: str) -> ToolAdapter:
        return registry()[name](self.settings)

    def tools_for(self, target_type: TargetType) -> list[str]:
        """Enabled tools that accept ``target_type``."""
        return [n for n, cls in registry().items()
                if target_type in cls.input_types and self.settings.tool_enabled(n)]

    # ------------------------------------------------------------ public API (thread-safe)
    def submit(self, target: str, target_type: TargetType, tools: list[str], parent_id: int | None = None) -> int:
        """Create a scan and start it. Returns the scan id immediately."""
        known = registry()
        tools = [t for t in dict.fromkeys(tools) if t in known]
        if not tools:
            raise ValueError("Не выбрано ни одного инструмента")
        scan_id = self.storage.create_scan(target, target_type.value, tools, parent_id)
        self._emit(EngineEvent("scan_started", scan_id, data={"target": target, "target_type": target_type.value,
                                                              "tools": tools}))
        for tool in tools:
            self._schedule(scan_id, tool, target, target_type)
        return scan_id

    def retry(self, scan_id: int, tool: str) -> None:
        """Re-run one tool of an existing scan (e.g. after an error)."""
        rec = self.storage.get_scan(scan_id, with_results=False)
        if rec is None:
            raise KeyError(scan_id)
        if (scan_id, tool) in self._runs:
            return  # already running
        self.storage.reset_run(scan_id, tool)
        self._emit(EngineEvent("run_status", scan_id, tool, {"status": Status.QUEUED.value}))
        self._schedule(scan_id, tool, rec.target, TargetType(rec.target_type))

    def rerun(self, scan_id: int) -> int:
        """Start a fresh scan with the same target and tools."""
        rec = self.storage.get_scan(scan_id, with_results=False)
        if rec is None:
            raise KeyError(scan_id)
        return self.submit(rec.target, TargetType(rec.target_type), rec.tools, parent_id=rec.parent_id)

    def cancel(self, scan_id: int, tool: str | None = None) -> None:
        """Cancel one tool, or the whole scan if ``tool`` is None."""
        for (sid, t), run in list(self._runs.items()):
            if sid == scan_id and (tool is None or t == tool):
                run.ctx.cancelled.set()
                if run.task is not None:
                    self._loop.call_soon_threadsafe(run.task.cancel)

    def is_active(self, scan_id: int) -> bool:
        return any(sid == scan_id for sid, _ in list(self._runs))

    def active_scans(self) -> set[int]:
        return {sid for sid, _ in list(self._runs)}

    def run_log(self, scan_id: int, tool: str) -> list[str]:
        run = self._runs.get((scan_id, tool))
        return list(run.lines) if run else []

    # ------------------------------------------------------------ internals
    def _schedule(self, scan_id: int, tool: str, target: str, target_type: TargetType) -> None:
        adapter = self.adapter(tool)
        run = _Run(ctx=RunContext(tool=tool, target=target, target_type=target_type,
                                  timeout=float(adapter.timeout())))
        run.ctx.on_log = lambda level, msg: self._on_log(scan_id, tool, run, level, msg)
        run.ctx.on_progress = lambda frac, note: self._on_progress(scan_id, tool, run, frac, note)
        self._runs[(scan_id, tool)] = run

        def create() -> None:
            run.task = self._loop.create_task(self._run_tool(scan_id, adapter, run))

        self._loop.call_soon_threadsafe(create)

    async def _run_tool(self, scan_id: int, adapter: ToolAdapter, run: _Run) -> None:
        ctx, tool = run.ctx, adapter.name
        result: ToolResult | None = None
        try:
            assert self._sem is not None
            async with self._sem:
                ctx.check_cancelled()
                self.storage.set_run_status(scan_id, tool, Status.RUNNING.value, started_at=utcnow())
                self._emit(EngineEvent("run_status", scan_id, tool, {"status": Status.RUNNING.value}))
                result = await adapter.execute(ctx.target, ctx.target_type, ctx)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # engine bug — never leave a run hanging
            log.exception("engine failure in %s", tool)
            result = ToolResult(tool, ctx.target, Status.ERROR.value, finished_at=utcnow(),
                                error=f"Внутренняя ошибка: {exc}", target_type=ctx.target_type.value)
        if result is None:  # cancelled while queued
            result = ToolResult(tool, ctx.target, Status.CANCELLED.value, finished_at=utcnow(),
                                error="Остановлено пользователем", target_type=ctx.target_type.value)
        try:
            self.storage.save_result(scan_id, result, "\n".join(run.lines[-MAX_LOG_LINES:]))
        except Exception:
            log.exception("failed to save result for %s", tool)
        self._runs.pop((scan_id, tool), None)
        self._emit(EngineEvent("run_status", scan_id, tool, {
            "status": result.status, "error": result.error, "findings": len(result.findings)}))
        if not self.is_active(scan_id):
            rec = self.storage.get_scan(scan_id, with_results=False)
            self._emit(EngineEvent("scan_finished", scan_id, data={
                "status": rec.status if rec else Status.DONE.value,
                "findings": rec.findings_count if rec else 0}))

    def _on_log(self, scan_id: int, tool: str, run: _Run, level: str, msg: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"{stamp} [{level.upper()}] {msg}"
        run.lines.append(line)
        if len(run.lines) > MAX_LOG_LINES * 2:
            del run.lines[:MAX_LOG_LINES]
        self._emit(EngineEvent("log", scan_id, tool, {"time": stamp, "level": level, "message": msg}))

    def _on_progress(self, scan_id: int, tool: str, run: _Run, frac: float | None, note: str) -> None:
        now = time.monotonic()
        if frac != 1.0 and now - run.last_progress < PROGRESS_INTERVAL:
            return
        run.last_progress = now
        self._emit(EngineEvent("progress", scan_id, tool, {"fraction": frac, "note": note}))
