"""End-to-end smoke test: run each adapter through the real ScanEngine.

    python scripts/smoke_test.py                 # all tools, default test inputs
    python scripts/smoke_test.py sherlock=octocat
    python scripts/smoke_test.py --save-fixtures # also store raw output in tests/fixtures

Uses a throw-away data directory, so your real history is untouched.
Default inputs are public/reserved values (example.com, GitHub's mascot
"octocat", a public company switchboard) — not private individuals.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OSINTHUB_DATA_DIR", tempfile.mkdtemp(prefix="osinthub-smoke-"))

from app.config import Settings  # noqa: E402
from app.core.runner import EngineEvent, ScanEngine  # noqa: E402
from app.core.schema import TargetType  # noqa: E402
from app.core.storage import Storage  # noqa: E402

DEFAULTS = {
    "exiftool": (str(ROOT / "tests" / "fixtures" / "files" / "trip_тест.jpg"), TargetType.FILE),
    "phoneinfoga": ("+16502530000", TargetType.PHONE),
    "holehe": ("test@example.com", TargetType.EMAIL),
    "sherlock": ("octocat", TargetType.USERNAME),
    "spiderfoot": ("example.com", TargetType.DOMAIN),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("overrides", nargs="*", help="tool=value")
    ap.add_argument("--save-fixtures", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    jobs = dict(DEFAULTS)
    selected = set()
    for o in args.overrides:
        tool, _, value = o.partition("=")
        selected.add(tool)
        if value:
            jobs[tool] = (value, jobs[tool][1])
    if selected:
        jobs = {k: v for k, v in jobs.items() if k in selected}

    settings = Settings()
    for tool in jobs:
        settings.set_tool_option(tool, "timeout", args.timeout, save=False)
    storage = Storage()
    done = threading.Event()
    pending: set[int] = set()
    lock = threading.Lock()

    def listener(ev: EngineEvent) -> None:
        if ev.kind == "log" and ev.data["level"] in ("error", "warn", "done", "run"):
            print(f"  [{ev.tool}] {ev.data['level']:5} {ev.data['message'][:160]}", flush=True)
        elif ev.kind == "scan_finished":
            with lock:
                pending.discard(ev.scan_id)
                if not pending:
                    done.set()

    engine = ScanEngine(settings, storage, listener)
    engine.start()
    started = time.monotonic()
    ids: dict[str, int] = {}
    with lock:
        for tool, (value, ttype) in jobs.items():
            ids[tool] = engine.submit(value, ttype, [tool])
            pending.add(ids[tool])
    done.wait(args.timeout + 60)
    engine.stop()

    print(f"\n=== Итог ({time.monotonic() - started:.0f} с) ===")
    ok = True
    for tool, scan_id in ids.items():
        rec = storage.get_scan(scan_id)
        assert rec is not None
        res = rec.results[tool]
        types: dict[str, int] = {}
        for f in res.findings:
            types[f.type] = types.get(f.type, 0) + 1
        print(f"{tool:12} {res.status:9} находок={len(res.findings):4} {types} {res.error or ''}")
        for f in res.findings[:5]:
            print(f"{'':14}- {f.type:9} {f.value[:90]}  ({f.source}, {f.confidence})")
        ok &= res.status == "done"
        if args.save_fixtures and res.raw is not None:
            out = ROOT / "tests" / "fixtures" / f"{tool}_raw.json"
            out.write_text(json.dumps(res.raw, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
