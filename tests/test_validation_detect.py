import pytest

from app.core import validation as v
from app.core.detect import detect
from app.core.schema import TargetType


@pytest.mark.parametrize("text,expected,value", [
    ("Marina.Voronina@Example.ORG", TargetType.EMAIL, "Marina.Voronina@example.org"),
    ("+7 900 000-00-00", TargetType.PHONE, "+79000000000"),
    ("8 (900) 123-45-67", TargetType.PHONE, "+79001234567"),
    ("@marina_v", TargetType.USERNAME, "marina_v"),
    ("octocat", TargetType.USERNAME, "octocat"),
    ("northwind.example", TargetType.DOMAIN, "northwind.example"),
    ("https://www.Example.com/path", TargetType.DOMAIN, "example.com"),
    ("пример.рф", TargetType.DOMAIN, "xn--e1afmkfd.xn--p1ai"),
    ("8.8.8.8", TargetType.IP, "8.8.8.8"),
    ("2001:db8::1", TargetType.IP, "2001:db8::1"),
])
def test_detect(text, expected, value):
    d = detect(text, "RU")
    assert d.type is expected
    assert d.value == value


def test_detect_ambiguous_offers_alternatives():
    d = detect("john.doe")
    assert d.type is TargetType.DOMAIN
    assert TargetType.USERNAME in d.alternatives


def test_detect_short_number_is_not_phone():
    assert detect("2024").type is TargetType.USERNAME


def test_detect_file(tmp_path):
    f = tmp_path / "фото.jpg"
    f.write_bytes(b"x")
    assert detect(str(f)).type is TargetType.FILE


def test_detect_garbage():
    d = detect("hello world; rm -rf /")
    assert d.type is None and d.error


@pytest.mark.parametrize("bad", [
    "-rf", "--help", "a b", "x;y", "$(whoami)", "`id`", "a|b", "a\nb", "x" * 300, "",
])
def test_username_rejects_injection(bad):
    with pytest.raises(v.ValidationError):
        v.normalize_username(bad)


@pytest.mark.parametrize("bad", ["-x@example.com", "a@b", "a@@b.com", "a@b.c", "a b@c.com"])
def test_email_rejects(bad):
    with pytest.raises(v.ValidationError):
        v.normalize_email(bad)


@pytest.mark.parametrize("bad", ["-example.com", "exa mple.com", "localhost", "a..com", "example.123"])
def test_domain_rejects(bad):
    with pytest.raises(v.ValidationError):
        v.normalize_domain(bad)


@pytest.mark.parametrize("bad", ["+7 900 abc", "12", "+1 (555) 0; ls"])
def test_phone_rejects(bad):
    with pytest.raises(v.ValidationError):
        v.normalize_phone(bad, "RU")


def test_file_size_limit(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"0" * 2048)
    assert v.normalize_file(str(f), 4096) == str(f.resolve())
    with pytest.raises(v.ValidationError):
        v.normalize_file(str(f), 1024)
    with pytest.raises(v.ValidationError):
        v.normalize_file(str(tmp_path / "missing.jpg"))
    with pytest.raises(v.ValidationError):
        v.normalize_file(str(tmp_path))
