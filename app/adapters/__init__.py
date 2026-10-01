"""Tool adapters. Every module in this package is imported automatically."""

from __future__ import annotations

import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)

_discovered = False

# Explicit list keeps PyInstaller happy even if pkgutil can't list frozen
# modules; new adapters are still found by the pkgutil scan below.
_BUILTIN = ("exiftool", "phoneinfoga", "holehe", "spiderfoot", "sherlock")


def discover() -> None:
    """Import every adapter module once so that subclasses self-register."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    names = set(_BUILTIN)
    names.update(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))
    names.discard("base")
    for name in sorted(names):
        try:
            importlib.import_module(f"{__name__}.{name}")
        except Exception:  # a broken adapter must not take down the app
            log.exception("Failed to load adapter %s", name)
