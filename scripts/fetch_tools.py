"""Download and install the bundled third-party tools into ``tools/``.

Usage::

    python scripts/fetch_tools.py            # install everything missing
    python scripts/fetch_tools.py --force    # reinstall everything
    python scripts/fetch_tools.py exiftool   # only selected tools

What gets installed (versions are pinned below — bump them to update):

* ``tools/exiftool/``     exiftool.exe + exiftool_files (official Windows build)
* ``tools/phoneinfoga/``  phoneinfoga.exe (official GitHub release)
* ``tools/spiderfoot/``   embeddable CPython 3.11 + SpiderFoot source + its
                          pinned dependencies, isolated from the main app.

Every archive is verified against the vendor-published SHA-256 checksum
(ExifTool, PhoneInfoga) or against the hash pinned in this file.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

EXIFTOOL_VERSION = "13.59"
PHONEINFOGA_VERSION = "2.11.0"
SPIDERFOOT_COMMIT = "0f815a203afebf05c98b605dba5cf0475a0ee5fd"  # master, 2023-11-05
SPIDERFOOT_SHA256 = "67f24cf0d9a54ae6f0635af65555951cc3ab64eb9fb76779d02b41a482fc6a3c"
PYTHON_EMBED_VERSION = "3.11.9"
PYTHON_EMBED_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"

USER_AGENT = "OSINTHub-fetch-tools/1.0"


def log(msg: str) -> None:
    print(f"[fetch] {msg}", flush=True)


def download(url: str) -> bytes:
    """Download ``url`` into memory."""
    log(f"GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    log(f"    {len(data) / 1_048_576:.1f} MB")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(data: bytes, expected: str, name: str) -> None:
    actual = sha256(data)
    if not expected:
        log(f"WARNING: no pinned hash for {name}; sha256={actual}")
        return
    if actual.lower() != expected.lower():
        raise SystemExit(f"Checksum mismatch for {name}: expected {expected}, got {actual}")
    log(f"    sha256 OK ({name})")


# --------------------------------------------------------------------------- ExifTool
def install_exiftool(force: bool) -> None:
    dest = TOOLS / "exiftool"
    if (dest / "exiftool.exe").exists() and not force:
        log("exiftool: already installed")
        return
    name = f"exiftool-{EXIFTOOL_VERSION}_64.zip"
    sums = download("https://exiftool.org/checksums.txt").decode("utf-8", "replace")
    m = re.search(rf"SHA2-256\({re.escape(name)}\)\s*=\s*([0-9a-f]{{64}})", sums)
    if not m:
        raise SystemExit(f"No SHA-256 for {name} in exiftool.org/checksums.txt")
    data = b""
    for url in (f"https://sourceforge.net/projects/exiftool/files/{name}/download",
                f"https://exiftool.org/{name}"):
        try:
            data = download(url)
            if data[:2] == b"PK":  # a real zip, not a mirror-selection HTML page
                break
        except OSError as exc:
            log(f"    failed: {exc}")
    verify(data, m.group(1), name)

    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf, tempfile.TemporaryDirectory() as tmp:
        zf.extractall(tmp)
        root = next(Path(tmp).iterdir())
        exe = next(root.glob("exiftool*.exe"))
        shutil.copy2(exe, dest / "exiftool.exe")  # drop the "(-k)" pause-on-exit suffix
        shutil.copytree(root / "exiftool_files", dest / "exiftool_files")
    (dest / "VERSION").write_text(EXIFTOOL_VERSION, encoding="utf-8")
    log(f"exiftool {EXIFTOOL_VERSION} -> {dest}")


# --------------------------------------------------------------------------- PhoneInfoga
def install_phoneinfoga(force: bool) -> None:
    dest = TOOLS / "phoneinfoga"
    if (dest / "phoneinfoga.exe").exists() and not force:
        log("phoneinfoga: already installed")
        return
    base = f"https://github.com/sundowndev/phoneinfoga/releases/download/v{PHONEINFOGA_VERSION}"
    name = "phoneinfoga_Windows_x86_64.tar.gz"
    sums = download(f"{base}/phoneinfoga_checksums.txt").decode("utf-8", "replace")
    m = re.search(rf"([0-9a-f]{{64}})\s+{re.escape(name)}", sums)
    if not m:
        raise SystemExit(f"No checksum for {name}")
    data = download(f"{base}/{name}")
    verify(data, m.group(1), name)

    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("phoneinfoga.exe"))
        src = tf.extractfile(member)
        assert src is not None
        (dest / "phoneinfoga.exe").write_bytes(src.read())
    # GPL-3.0 requires shipping the licence text with the binary.
    lic = download(f"https://raw.githubusercontent.com/sundowndev/phoneinfoga/v{PHONEINFOGA_VERSION}/LICENSE")
    (dest / "LICENSE").write_bytes(lic)
    (dest / "VERSION").write_text(PHONEINFOGA_VERSION, encoding="utf-8")
    log(f"phoneinfoga {PHONEINFOGA_VERSION} -> {dest}")


# --------------------------------------------------------------------------- SpiderFoot
SF_CONFIG_HELPER = '''"""OSINT Hub helper: write module API keys into SpiderFoot's config DB.

Reads a JSON object {"sfp_module:option": "value", ...} from stdin so that
secrets never appear on a command line. Runs inside SpiderFoot's own runtime.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "spiderfoot"))

from spiderfoot import SpiderFootDb, SpiderFootHelpers  # noqa: E402

opts = json.load(sys.stdin)
db = SpiderFootDb({"__database": os.path.join(SpiderFootHelpers.dataPath(), "spiderfoot.db")})
current = db.configGet() or {}
current.update({k: str(v) for k, v in opts.items() if ":" in k})
current = {k: v for k, v in current.items() if v != ""}
db.configClear()
db.configSet(current)
print("ok", len(opts))
'''


def install_spiderfoot(force: bool) -> None:
    dest = TOOLS / "spiderfoot"
    py = dest / "python" / "python.exe"
    if (dest / "spiderfoot" / "sf.py").exists() and py.exists() and not force:
        log("spiderfoot: already installed")
        return
    shutil.rmtree(dest, ignore_errors=True)
    (dest / "python").mkdir(parents=True)

    # 1. Embeddable CPython (isolated from the app's own interpreter).
    name = f"python-{PYTHON_EMBED_VERSION}-embed-amd64.zip"
    data = download(f"https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/{name}")
    verify(data, PYTHON_EMBED_SHA256, name)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest / "python")
    pth = next((dest / "python").glob("python3*._pth"))
    pth.write_text(
        "\n".join([pth.stem.replace("._pth", "") + ".zip", ".", "Lib\\site-packages", "..\\spiderfoot", "import site", ""]),
        encoding="utf-8",
    )

    # 2. SpiderFoot source at a pinned commit.
    data = download(f"https://codeload.github.com/smicallef/spiderfoot/zip/{SPIDERFOOT_COMMIT}")
    verify(data, SPIDERFOOT_SHA256, "spiderfoot.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as zf, tempfile.TemporaryDirectory() as tmp:
        zf.extractall(tmp)
        shutil.copytree(next(Path(tmp).iterdir()), dest / "spiderfoot")

    # 3. pip + SpiderFoot's pinned requirements inside the embedded runtime.
    get_pip = dest / "get-pip.py"
    get_pip.write_bytes(download("https://bootstrap.pypa.io/get-pip.py"))
    run([str(py), str(get_pip), "--no-warn-script-location", "-q"])
    get_pip.unlink()
    run([str(py), "-m", "pip", "install", "-q", "--no-warn-script-location",
         "-r", str(dest / "spiderfoot" / "requirements.txt")])

    (dest / "osinthub_sf_config.py").write_text(SF_CONFIG_HELPER, encoding="utf-8")
    (dest / "VERSION").write_text(f"4.0+{SPIDERFOOT_COMMIT[:7]}", encoding="utf-8")
    log(f"spiderfoot {SPIDERFOOT_COMMIT[:7]} -> {dest}")


def run(args: list[str]) -> None:
    log("$ " + " ".join(args))
    subprocess.run(args, check=True)


INSTALLERS = {
    "exiftool": install_exiftool,
    "phoneinfoga": install_phoneinfoga,
    "spiderfoot": install_spiderfoot,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tools", nargs="*", help=f"tools to install: {', '.join(INSTALLERS)} (default: all)")
    ap.add_argument("--force", action="store_true", help="reinstall even if present")
    args = ap.parse_args()
    unknown = set(args.tools) - set(INSTALLERS)
    if unknown:
        ap.error(f"unknown tool(s): {', '.join(sorted(unknown))}")
    TOOLS.mkdir(exist_ok=True)
    for name in args.tools or INSTALLERS:
        INSTALLERS[name](args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
