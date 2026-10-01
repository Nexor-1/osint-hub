"""Scan engine, storage, related findings and export — with fake adapters."""

import asyncio
import json
import threading

import pytest

from app.adapters.base import ToolAdapter
from app.core import export
from app.core.related import find_pivots
from app.core.runner import ScanEngine
from app.core.schema import Finding, TargetType, ToolResult
from app.core.storage import Storage, aggregate_status


class FakeOk(ToolAdapter):
    name = "fake_ok"
    title = "FakeOk"
    input_types = frozenset({TargetType.USERNAME, TargetType.EMAIL})

    async def run(self, target, ctx):
        ctx.progress(0.5, "half")
        ctx.log("[FOUND] something", "found")
        return {"items": [f"{target}@example.org", "other_nick"]}

    def parse_output(self, raw):
        return [Finding("email", raw["items"][0], "fake"), Finding("username", raw["items"][1], "fake"),
                Finding("email", raw["items"][0], "fake")]  # duplicate is dropped


class FakeSlow(ToolAdapter):
    name = "fake_slow"
    title = "FakeSlow"
    input_types = frozenset({TargetType.USERNAME})
    default_timeout = 1

    async def run(self, target, ctx):
        ctx.partial = {"items": ["partial@example.org"]}
        await asyncio.sleep(30)

    def parse_output(self, raw):
        return [Finding("email", x, "slow") for x in raw["items"]]


class FakeCrash(ToolAdapter):
    name = "fake_crash"
    title = "FakeCrash"
    input_types = frozenset({TargetType.USERNAME})

    async def run(self, target, ctx):
        raise ZeroDivisionError("boom")

    def parse_output(self, raw):
        return []


class FakeMissing(ToolAdapter):
    name = "fake_missing"
    title = "FakeMissing"
    input_types = frozenset({TargetType.USERNAME})

    def availability(self):
        return False, "нет файла fake.exe"

    async def run(self, target, ctx):
        raise AssertionError("must not run")

    def parse_output(self, raw):
        return []


class FakeHang(ToolAdapter):
    name = "fake_hang"
    title = "FakeHang"
    input_types = frozenset({TargetType.USERNAME})
    default_timeout = 60

    async def run(self, target, ctx):
        await asyncio.sleep(60)

    def parse_output(self, raw):
        return []


@pytest.fixture
def engine(tmp_path, settings):
    storage = Storage(tmp_path / "t.db")
    events = []
    finished = {}
    cond = threading.Condition()

    def listener(ev):
        with cond:
            events.append(ev)
            if ev.kind == "scan_finished":
                finished[ev.scan_id] = ev
                cond.notify_all()

    eng = ScanEngine(settings, storage, listener)
    eng.start()

    def wait(scan_id, timeout=15):
        with cond:
            assert cond.wait_for(lambda: scan_id in finished, timeout), "scan did not finish"
        return storage.get_scan(scan_id)

    eng.wait = wait
    eng.events = events
    yield eng
    eng.stop()
    storage.close()


def test_errors_are_isolated_per_tool(engine):
    sid = engine.submit("marina_v", TargetType.USERNAME, ["fake_ok", "fake_slow", "fake_crash", "fake_missing"])
    rec = engine.wait(sid)
    r = rec.results
    assert r["fake_ok"].status == "done" and len(r["fake_ok"].findings) == 2
    assert r["fake_slow"].status == "error" and "таймаут" in r["fake_slow"].error
    assert [f.value for f in r["fake_slow"].findings] == ["partial@example.org"]  # salvaged
    assert r["fake_crash"].status == "error" and "ZeroDivisionError" in r["fake_crash"].error
    assert r["fake_missing"].status == "error" and "не установлен" in r["fake_missing"].error
    assert rec.status == "done"  # partial success
    kinds = {e.kind for e in engine.events}
    assert {"scan_started", "run_status", "progress", "log", "scan_finished"} <= kinds


def test_invalid_input_reported(engine):
    sid = engine.submit("bad nick; rm", TargetType.USERNAME, ["fake_ok"])
    rec = engine.wait(sid)
    assert rec.results["fake_ok"].status == "error"
    assert rec.results["fake_ok"].error.startswith("Некорректный ввод")


def test_cancel_and_retry(engine):
    sid = engine.submit("nick", TargetType.USERNAME, ["fake_hang"])
    import time
    time.sleep(0.3)
    engine.cancel(sid)
    rec = engine.wait(sid)
    assert rec.results["fake_hang"].status == "cancelled"
    assert rec.status == "cancelled"


def test_retry_failed_tool(engine):
    sid = engine.submit("nick", TargetType.USERNAME, ["fake_crash"])
    engine.wait(sid)
    engine.retry(sid, "fake_crash")
    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        rec = engine.storage.get_scan(sid)
        if rec.results["fake_crash"].status == "error" and rec.runs["fake_crash"].started_at:
            break
        time.sleep(0.05)
    assert rec.results["fake_crash"].status == "error"


def test_history_and_delete(engine):
    a = engine.submit("alpha_nick", TargetType.USERNAME, ["fake_ok"])
    b = engine.submit("beta@example.org", TargetType.EMAIL, ["fake_ok"])
    engine.wait(a), engine.wait(b)
    s = engine.storage
    assert [r.id for r in s.list_scans("alpha")] == [a]
    assert [r.id for r in s.list_scans(target_type="email")] == [b]
    assert s.list_scans("%") == []  # LIKE wildcards are escaped
    assert s.list_scans()[0].findings_count == 2
    new_id = engine.rerun(a)
    assert engine.wait(new_id).target == "alpha_nick"
    s.delete_scan(a)
    assert s.get_scan(a) is None


def test_aggregate_status():
    assert aggregate_status(["done", "error"]) == "done"
    assert aggregate_status(["error", "error"]) == "error"
    assert aggregate_status(["running", "done"]) == "running"
    assert aggregate_status(["cancelled"]) == "cancelled"


def test_related_pivots():
    res = ToolResult("x", "marina.voronina@example.org", findings=[
        Finding("username", "marina_v", "GitHub"),
        Finding("email", "m*****a@gmail.com", "Holehe", extra={"masked": True}),
        Finding("email", "marina.voronina@example.org", "SpiderFoot"),  # the target itself
        Finding("email", "work@northwind.example", "SpiderFoot"),
        Finding("domain", "gmail.com", "SpiderFoot"),
        Finding("phone", "+7 *** ** 67", "Holehe"),
    ])
    tools = {TargetType.USERNAME: ["sherlock"], TargetType.EMAIL: ["holehe"], TargetType.DOMAIN: ["spiderfoot"]}
    pivots = find_pivots("marina.voronina@example.org", TargetType.EMAIL, [res], tools)
    got = [(p.type, p.value) for p in pivots]
    assert got == [(TargetType.USERNAME, "marina.voronina"), (TargetType.USERNAME, "marina_v"),
                   (TargetType.EMAIL, "work@northwind.example")]
    assert pivots[0].tools == ["sherlock"]


def test_export_json_and_html(engine, tmp_path):
    sid = engine.submit("evil<script>", TargetType.USERNAME, ["fake_ok"])  # invalid → error result
    sid2 = engine.submit("nick", TargetType.USERNAME, ["fake_ok"])
    engine.wait(sid), engine.wait(sid2)
    rec = engine.storage.get_scan(sid2)
    rec.results["fake_ok"].findings.append(Finding("other", "<img src=x onerror=alert(1)>", "x"))

    p = tmp_path / "r.json"
    export.export(rec, p, "json", export.ExportOptions(log=True))
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["scan"]["target"] == "nick" and data["summary"]["total_findings"] == 3
    assert "log" in data and "raw" in data

    h = tmp_path / "r.html"
    export.export(rec, h, "html", export.ExportOptions(metadata=False))
    html = h.read_text(encoding="utf-8")
    assert "nick@example.org" in html and "&lt;img src=x" in html and "<img src=x" not in html
    assert "Сырой вывод" not in html
    with pytest.raises(ValueError):
        export.export(rec, tmp_path / "r.pdf", "pdf")
