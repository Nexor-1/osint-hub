"""Holehe adapter run(): concurrent modules must not duplicate/misattribute results."""

import asyncio
import random

from app.adapters import holehe as holehe_mod
from app.adapters.base import RunContext
from app.core.schema import TargetType


def _make_module(name: str, exists: bool):
    async def module(email, client, out):
        await asyncio.sleep(random.random() / 50)
        out.append({"name": name, "domain": f"{name}.com", "exists": exists, "rateLimit": False})

    module.__name__ = name
    return module


def test_concurrent_modules_logged_once(settings, monkeypatch):
    mods = [_make_module(f"site{i}", i % 3 == 0) for i in range(30)]
    monkeypatch.setattr(holehe_mod, "_load_modules", lambda: mods)
    logs = []
    ctx = RunContext("holehe", "a@example.org", TargetType.EMAIL, 30,
                     on_log=lambda level, msg: logs.append((level, msg)))
    raw = asyncio.run(holehe_mod.HoleheAdapter(settings).run("a@example.org", ctx))
    found_logs = [m for lvl, m in logs if lvl == "found"]
    assert len(raw["results"]) == 30
    assert sorted(found_logs) == sorted(f"[FOUND] site{i}.com" for i in range(0, 30, 3))


def test_password_recovery_modules_excluded_by_default(settings, monkeypatch):
    mods = [_make_module("adobe", True), _make_module("github", True)]
    monkeypatch.setattr(holehe_mod, "_load_modules", lambda: mods)
    ctx = RunContext("holehe", "a@example.org", TargetType.EMAIL, 30)
    raw = asyncio.run(holehe_mod.HoleheAdapter(settings).run("a@example.org", ctx))
    assert [r["name"] for r in raw["results"]] == ["github"]
