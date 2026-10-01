"""Thread-safe bridge between the background ScanEngine and Qt widgets."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.runner import EngineEvent, ScanEngine


class EngineBridge(QObject):
    """Re-emits engine events as Qt signals (queued into the GUI thread)."""

    event = Signal(object)            # every EngineEvent
    scan_started = Signal(int)
    run_status = Signal(int, str, dict)
    progress = Signal(int, str, object, str)   # scan_id, tool, fraction|None, note
    log = Signal(int, str, dict)
    scan_finished = Signal(int, dict)
    history_changed = Signal()

    def __init__(self, engine: ScanEngine) -> None:
        super().__init__()
        self.engine = engine
        engine.add_listener(self._on_event)  # called from the engine thread

    def _on_event(self, ev: EngineEvent) -> None:
        # Emitting a signal from another thread is safe: Qt queues it to
        # receivers living in the GUI thread.
        self.event.emit(ev)
        if ev.kind == "scan_started":
            self.scan_started.emit(ev.scan_id)
            self.history_changed.emit()
        elif ev.kind == "run_status":
            self.run_status.emit(ev.scan_id, ev.tool or "", ev.data)
        elif ev.kind == "progress":
            self.progress.emit(ev.scan_id, ev.tool or "", ev.data.get("fraction"), ev.data.get("note", ""))
        elif ev.kind == "log":
            self.log.emit(ev.scan_id, ev.tool or "", ev.data)
        elif ev.kind == "scan_finished":
            self.scan_finished.emit(ev.scan_id, ev.data)
            self.history_changed.emit()
