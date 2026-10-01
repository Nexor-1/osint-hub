"""Application paths, user settings and secrets.

* Non-secret settings live in ``%APPDATA%\\OSINTHub\\settings.json`` and are
  editable from the Settings page.
* Secrets (API keys) are stored in Windows Credential Manager via ``keyring``.
  A value from the environment / ``.env`` always takes precedence, so CI or
  power users can inject keys without touching the UI. Nothing is hard-coded.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

log = logging.getLogger(__name__)

APP_NAME = "OSINTHub"
APP_TITLE = "OSINT Hub"
APP_VERSION = "1.0.0"
APP_REPO = "https://github.com/Nexor-1/osint-hub"
APP_LICENSE = "GPL-3.0"
KEYRING_SERVICE = "OSINTHub"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Directory containing the executable (frozen) or the repo root (source)."""
    if _frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Bundled read-only resources (PyInstaller ``_internal`` or the repo)."""
    if _frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return app_dir()


# .env next to the executable / repo root, then the user data dir.
load_dotenv(app_dir() / ".env", override=False)


def data_dir() -> Path:
    """Per-user writable data directory (``%APPDATA%\\OSINTHub``)."""
    override = os.environ.get("OSINTHUB_DATA_DIR")
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def tools_dir() -> Path:
    """Folder with bundled third-party tools (``tools/`` next to the program)."""
    override = os.environ.get("OSINTHUB_TOOLS_DIR")
    return Path(override) if override else app_dir() / "tools"


load_dotenv(data_dir() / ".env", override=False)


@dataclass(frozen=True, slots=True)
class SecretSpec:
    """Declares a secret an adapter needs. ``env`` is the environment variable name."""

    key: str
    label: str
    env: str
    help: str = ""


DEFAULTS: dict[str, Any] = {
    "disclaimer_accepted": False,
    "default_region": "RU",
    "max_parallel_tools": 3,
    "max_file_mb": 100,
    "tools": {},  # per-tool: {"enabled": bool, "timeout": int, ...adapter options}
}


class Settings:
    """Thread-safe JSON-backed settings store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "settings.json"
        self._lock = threading.RLock()
        self._data: dict[str, Any] = json.loads(json.dumps(DEFAULTS))
        self.load()

    # -- persistence -----------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self._data.update(loaded)
                except (OSError, ValueError) as exc:
                    log.warning("settings.json unreadable, using defaults: %s", exc)

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    # -- generic access --------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if save:
                self.save()

    # -- per-tool options ------------------------------------------------
    def tool(self, name: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data.setdefault("tools", {}).get(name, {}))

    def tool_option(self, name: str, option: str, default: Any = None) -> Any:
        return self.tool(name).get(option, default)

    def set_tool_option(self, name: str, option: str, value: Any, *, save: bool = True) -> None:
        with self._lock:
            self._data.setdefault("tools", {}).setdefault(name, {})[option] = value
            if save:
                self.save()

    def tool_enabled(self, name: str) -> bool:
        return bool(self.tool_option(name, "enabled", True))

    # -- secrets -----------------------------------------------------------
    def secret(self, spec: SecretSpec) -> str:
        """Return a secret: environment first, then Windows Credential Manager."""
        env = os.environ.get(spec.env, "").strip()
        if env:
            return env
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, spec.key) or ""
        except Exception as exc:  # keyring backend missing / locked
            log.warning("keyring unavailable: %s", exc)
            return ""

    def secret_source(self, spec: SecretSpec) -> str:
        """``"env"``, ``"keyring"`` or ``""`` — shown in the Settings UI."""
        if os.environ.get(spec.env, "").strip():
            return "env"
        try:
            import keyring

            return "keyring" if keyring.get_password(KEYRING_SERVICE, spec.key) else ""
        except Exception:
            return ""

    def set_secret(self, spec: SecretSpec, value: str) -> None:
        import keyring

        value = value.strip()
        if value:
            keyring.set_password(KEYRING_SERVICE, spec.key, value)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, spec.key)
            except Exception:
                pass
