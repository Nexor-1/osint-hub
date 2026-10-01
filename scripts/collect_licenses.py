"""Collect licence texts of every Python package bundled into OSINTHub.exe.

    python scripts/collect_licenses.py

Walks the runtime dependency closure of requirements.txt in the current
environment and copies each package's LICENSE / COPYING / NOTICE files (from
its dist-info) into ``licenses/python/<package>-<version>.txt``, plus an
index ``licenses/python/INDEX.md``. build.bat runs this before packaging so
the shipped app always carries the notices of exactly what it contains.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "licenses" / "python"
LICENSE_RE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.I)
# Excluded from the PyInstaller build (see build/osinthub.spec) together with their own deps.
EXCLUDED = {"pandas", "numpy", "openpyxl"}
FULL_TEXTS = {"GPL": "LICENSE (GNU GPL v3)", "LGPL": "licenses/LGPL-3.0.txt"}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def top_requirements() -> list[str]:
    names = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(Requirement(line).name)
    return names


def closure(names: list[str]) -> dict[str, md.Distribution]:
    env = default_environment()
    env["extra"] = ""
    seen: dict[str, md.Distribution] = {}
    todo = list(names)
    while todo:
        name = norm(todo.pop())
        if name in seen or name in EXCLUDED:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[name] = dist
        for req in dist.requires or []:
            r = Requirement(req)
            if r.marker is None or r.marker.evaluate(env):
                todo.append(r.name)
    return seen


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()
    rows = []
    for name, dist in sorted(closure(top_requirements()).items()):
        meta = dist.metadata
        lic = meta.get("License-Expression") or meta.get("License") or ""
        if len(lic) > 80 or "\n" in lic:  # some packages paste the whole text here
            lic = lic.splitlines()[0][:80]
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
        lic = lic or ", ".join(classifiers) or "см. текст"
        texts = []
        for f in dist.files or []:
            if LICENSE_RE.search(f.name) and not f.name.endswith((".py", ".pyc")):
                try:
                    text = Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")
                    texts.append(f"===== {f} =====\n{text}")
                except (OSError, ValueError):
                    pass
        home = meta.get("Home-page") or next((u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or []
                                              if u.lower().startswith(("source", "homepage", "repository"))), "")
        fname = f"{dist.metadata['Name']}-{dist.version}.txt"
        header = f"{dist.metadata['Name']} {dist.version}\nLicense: {lic}\nSource: {home}\n\n"
        ref = next((f for k, f in (("LGPL", FULL_TEXTS["LGPL"]), ("GPL", FULL_TEXTS["GPL"])) if k in lic.upper()), None)
        body = "\n\n".join(texts) or (f"Полный текст лицензии: {ref} в корне OSINT Hub." if ref else
                                      "(в пакете нет отдельного файла лицензии; см. исходный код по ссылке выше)")
        (OUT / fname).write_text(header + body + "\n", encoding="utf-8")
        rows.append(f"| {dist.metadata['Name']} | {dist.version} | {lic} | {home} |")
    # The CPython runtime embedded by PyInstaller.
    psf = Path(sys.base_prefix) / "LICENSE.txt"
    if psf.exists():
        (OUT / f"Python-{sys.version.split()[0]}.txt").write_text(
            f"Python {sys.version.split()[0]}\nLicense: PSF-2.0\nSource: https://www.python.org/\n\n"
            + psf.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        rows.insert(0, f"| Python (CPython) | {sys.version.split()[0]} | PSF-2.0 | https://www.python.org/ |")
    index = ["# Python-пакеты в составе OSINTHub.exe", "", "| Пакет | Версия | Лицензия | Исходный код |",
             "|---|---|---|---|", *rows, ""]
    (OUT / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    print(f"licenses: {len(rows)} packages -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
