"""Shared services handed to every page."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..adapters.base import ToolAdapter, registry
from ..config import Settings
from ..core.runner import ScanEngine
from ..core.schema import TargetType
from ..core.storage import Storage
from .bridge import EngineBridge

if TYPE_CHECKING:
    from .main_window import MainWindow


@dataclass
class AppContext:
    settings: Settings
    storage: Storage
    engine: ScanEngine
    bridge: EngineBridge
    window: "MainWindow | None" = None
    _adapters: dict[str, ToolAdapter] = field(default_factory=dict)

    # ------------------------------------------------------------ navigation
    def go(self, page: str, **kwargs: Any) -> None:
        assert self.window is not None
        self.window.navigate(page, **kwargs)

    def toast(self, text: str, kind: str = "success") -> None:
        if self.window is not None:
            self.window.toast.show_message(text, kind)

    # ------------------------------------------------------------ tools
    def adapters(self) -> dict[str, ToolAdapter]:
        """One adapter instance per registered tool (cheap, stateless)."""
        for name, cls in registry().items():
            if name not in self._adapters:
                self._adapters[name] = cls(self.settings)
        return self._adapters

    def adapter(self, name: str) -> ToolAdapter | None:
        return self.adapters().get(name)

    def tool_ready(self, name: str) -> bool:
        a = self.adapter(name)
        return bool(a and self.settings.tool_enabled(name) and a.availability()[0])

    def tools_for(self, ttype: TargetType) -> list[str]:
        return [n for n, a in self.adapters().items() if ttype in a.input_types and self.tool_ready(n)]

    def tools_map(self) -> dict[TargetType, list[str]]:
        return {t: self.tools_for(t) for t in TargetType}

    # ------------------------------------------------------------ scans
    def start_scan(self, target: str, ttype: TargetType, tools: list[str], parent_id: int | None = None,
                   *, open_page: bool = True) -> int | None:
        try:
            scan_id = self.engine.submit(target, ttype, tools, parent_id)
        except ValueError as exc:
            self.toast(str(exc), "error")
            return None
        if open_page:
            self.go("scan", scan_id=scan_id)
        return scan_id

    def open_scan(self, scan_id: int) -> None:
        """Open a scan: live view while running, results when finished."""
        if self.engine.is_active(scan_id):
            self.go("scan", scan_id=scan_id)
        else:
            self.go("results", scan_id=scan_id)

    def scan_chain_targets(self, scan_id: int) -> list[str]:
        """Targets of a scan and all its parents (to avoid suggesting them again)."""
        out: list[str] = []
        seen: set[int] = set()
        sid: int | None = scan_id
        while sid is not None and sid not in seen:
            seen.add(sid)
            rec = self.storage.get_scan(sid, with_results=False)
            if rec is None:
                break
            out.append(rec.target)
            sid = rec.parent_id
        return out
