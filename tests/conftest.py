"""Test configuration: isolate the data directory before the app is imported."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ["OSINTHUB_DATA_DIR"] = tempfile.mkdtemp(prefix="osinthub-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixture_json():
    return lambda name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path):
    from app.config import Settings

    return Settings(tmp_path / "settings.json")
