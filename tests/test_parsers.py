"""Parser tests for every adapter, against real (and a few synthetic) tool outputs."""

import json

import pytest

from app.adapters.exiftool import ExifToolAdapter, extract_gps
from app.adapters.holehe import HoleheAdapter
from app.adapters.phoneinfoga import PhoneInfogaAdapter, parse_console
from app.adapters.sherlock import SherlockAdapter
from app.adapters.spiderfoot import SpiderFootAdapter, parse_events


def by_type(findings, t):
    return [f for f in findings if f.type == t]


# ----------------------------------------------------------------- ExifTool
def test_exiftool_photo(settings, fixture_json):
    meta = fixture_json("exiftool_photo.json")[0]
    findings = ExifToolAdapter(settings).parse_output({"file": "x.jpg", "metadata": meta})

    geo = by_type(findings, "geo")
    assert len(geo) == 1
    assert geo[0].value == "55.751200, 37.618400"
    assert geo[0].extra["lat"] == pytest.approx(55.7512) and geo[0].extra["alt"] == 152

    values = {f.extra.get("field"): f.value for f in findings}
    assert values["Производитель"] == "Apple"
    assert values["Модель"] == "iPhone 15 Pro"
    assert values["Снято"] == "2026-09-28 17:24:00"
    assert values["Часовой пояс"] == "+03:00"
    assert values["Автор"] == "Test Author"
    assert values["Программа"] == "Photos 9.0"
    assert [f.value for f in by_type(findings, "email")] == ["test.author@example.org"]
    # File-system dates of the local copy must not leak into findings.
    assert not any("System:" in f.extra.get("tag", "") for f in findings)
    # Duplicate lens (LensModel + Composite:LensID) is reported once.
    assert sum(1 for f in findings if f.extra.get("field") == "Объектив") == 1


def test_exiftool_gps_from_refs_and_southwest():
    meta = {"GPS:GPSLatitude": 33.8688, "GPS:GPSLatitudeRef": "South",
            "GPS:GPSLongitude": 151.2093, "GPS:GPSLongitudeRef": "West"}
    assert extract_gps(meta) == {"lat": -33.8688, "lon": -151.2093}


@pytest.mark.parametrize("meta", [{}, {"Composite:GPSLatitude": "+0.000000", "Composite:GPSLongitude": "+0.000000"},
                                  {"Composite:GPSLatitude": "+95", "Composite:GPSLongitude": "+10"}])
def test_exiftool_no_or_invalid_gps(meta):
    assert extract_gps(meta) is None


def test_exiftool_empty(settings):
    assert ExifToolAdapter(settings).parse_output({"metadata": {}}) == []
    assert ExifToolAdapter(settings).parse_output(None) == []


# ----------------------------------------------------------------- PhoneInfoga
def test_phoneinfoga_console_real_us(fixture_text):
    parsed = parse_console(fixture_text("phoneinfoga_us.txt"))
    assert parsed["succeeded"] == 2
    assert parsed["scanners"]["local"]["fields"]["E164"] == "+16502530000"
    gs = parsed["scanners"]["googlesearch"]["sections"]
    assert set(gs) == {"Social media", "Disposable providers", "Reputation", "Individuals", "General"}
    assert all(item["URL"].startswith("https://www.google.com/search?") for items in gs.values() for item in items)


def test_phoneinfoga_errors_block(fixture_text):
    parsed = parse_console(fixture_text("phoneinfoga_errors.txt"))
    assert "numverify" in parsed["errors"]
    assert parsed["scanners"]["ovh"]["fields"]["Found"] == "false"


def test_phoneinfoga_findings_full(settings, fixture_text):
    findings = PhoneInfogaAdapter(settings).parse_output(fixture_text("phoneinfoga_full.txt"))
    assert [f.value for f in by_type(findings, "phone")] == ["+79001234567"]
    carriers = {f.value for f in by_type(findings, "carrier")}
    assert carriers == {"Tele2", "Tele2 Russia"}
    locations = {f.value for f in by_type(findings, "location")}
    assert {"RU", "Moscow, Russian Federation (the)", "75001 Paris"} <= locations
    cse = [f for f in by_type(findings, "url") if "Google CSE" in f.source]
    assert [f.extra["title"] for f in cse] == ["Contact — Example Shop", "+7 900 123-45-67 — forum"]


def test_phoneinfoga_dorks_are_low_confidence(settings, fixture_text):
    findings = PhoneInfogaAdapter(settings).parse_output(fixture_text("phoneinfoga_us.txt"))
    dorks = [f for f in findings if f.extra.get("kind") == "dork"]
    assert len(dorks) == 45 and all(f.confidence == "low" for f in dorks)


def test_phoneinfoga_ansi_colours_stripped():
    text = "\x1b[37mResults for local\n\x1b[0mE164: \x1b[33m+33142685300\n\x1b[0m\n1 scanner(s) succeeded\n"
    assert parse_console(text)["scanners"]["local"]["fields"]["E164"] == "+33142685300"


# ----------------------------------------------------------------- Holehe
def test_holehe_sample(settings, fixture_json):
    raw = fixture_json("holehe_sample.json")
    findings = HoleheAdapter(settings).parse_output(raw)
    accounts = {f.value: f.confidence for f in by_type(findings, "account")}
    assert accounts == {"github.com": "high", "instagram.com": "medium", "twitter.com": "high",
                        "en.gravatar.com": "high"}
    masked = by_type(findings, "email") + by_type(findings, "phone")
    assert len(masked) == 2 and all(f.extra["masked"] and f.confidence == "low" for f in masked)
    assert any(f.value == "FullName: Test Person" for f in by_type(findings, "other"))
    assert HoleheAdapter.stats(raw) == {"checked": 6, "found": 4, "unchecked": 1}


def test_holehe_real_output(settings, fixture_json):
    raw = fixture_json("holehe_raw.json")
    findings = HoleheAdapter(settings).parse_output(raw)
    found = [r for r in raw["results"] if r.get("exists")]
    assert len(by_type(findings, "account")) == len(found)


# ----------------------------------------------------------------- Sherlock
def test_sherlock_real_output(settings, fixture_json):
    raw = fixture_json("sherlock_raw.json")
    findings = SherlockAdapter(settings).parse_output(raw)
    claimed = [s for s in raw["sites"] if s["status"] == "Claimed"]
    assert len(findings) == len(claimed) > 0
    assert all(f.type == "account" and f.value.startswith("http") for f in findings)
    assert {f.confidence for f in findings} <= {"high", "medium"}


def test_sherlock_confidence_by_detection_method(settings):
    raw = {"username": "u", "sites": [
        {"site": "A", "url_user": "https://a/u", "status": "Claimed", "error_type": "status_code"},
        {"site": "B", "url_user": "https://b/u", "status": "Claimed", "error_type": "message"},
        {"site": "C", "url_user": "https://c/u", "status": "Available", "error_type": "message"},
        {"site": "D", "url_user": "https://d/u", "status": "Claimed", "error_type": ["message", "status_code"]},
    ]}
    conf = {f.source: f.confidence for f in SherlockAdapter(settings).parse_output(raw)}
    assert conf == {"A": "medium", "B": "high", "D": "high"}


# ----------------------------------------------------------------- SpiderFoot
def test_spiderfoot_stream_with_misplaced_brackets(fixture_text):
    text = fixture_text("spiderfoot_example_com.json")
    assert not text.lstrip().startswith("[")  # the real Windows quirk
    events = parse_events(text)
    assert len(events) > 20
    assert all({"type", "data", "module"} <= e.keys() for e in events)


def test_spiderfoot_findings(settings, fixture_text):
    findings = SpiderFootAdapter(settings).parse_output({"events": parse_events(fixture_text("spiderfoot_example_com.json"))})
    ips = {f.value for f in by_type(findings, "ip")}
    assert "8.6.112.0" in ips and "2a06:98c1:3122:8000::" in ips
    assert "registrar-abuse@cloudflare.com" in {f.value for f in by_type(findings, "email")}
    # root echo of the target and raw/bulky events are skipped
    assert not any(f.source.endswith("SpiderFoot UI") for f in findings)
    assert not any(f.extra.get("field") in ("Raw DNS Records", "Domain Whois") for f in findings)


def test_spiderfoot_account_url_extraction(settings):
    ev = {"type": "Account on External Site", "module": "sfp_accounts", "source": "u",
          "data": "GitHub (Category: coding)\n<SFURL>https://github.com/u</SFURL>"}
    [f] = SpiderFootAdapter(settings).parse_output({"events": [ev]})
    assert f.type == "account" and f.extra["url"] == "https://github.com/u"
    assert "<SFURL>" not in f.value


def test_spiderfoot_garbage_is_ignored():
    assert parse_events('[{not json},\n{"type": "IP Address", "data": "1.1.1.1", "module": "m"}]') == [
        {"type": "IP Address", "data": "1.1.1.1", "module": "m"}]


def test_spiderfoot_real_output(settings, fixture_json):
    findings = SpiderFootAdapter(settings).parse_output(fixture_json("spiderfoot_raw.json"))
    assert by_type(findings, "ip") and by_type(findings, "domain")
    assert json.dumps([f.to_dict() for f in findings], ensure_ascii=False)
