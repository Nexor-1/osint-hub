"""SpiderFoot adapter: automated collection around a domain, IP, email, phone or username.

SpiderFoot pins old dependencies (lxml<5, cryptography<4, pyOpenSSL<22) that
conflict with the rest of the app, so it lives in its own embeddable CPython
3.11 under ``tools/spiderfoot`` and is driven through its CLI::

    python sf.py -s <target> (-m <modules> | -u <use case>) -o json

Each event is printed to stdout as one JSON object per line, which gives live
progress. On Windows the scan runs in a ``multiprocessing`` child, so stdout
is *not* a well-formed JSON array (the parent's ``[``/``]`` come out at the
end) — :func:`parse_events` decodes objects one by one instead.

API keys from Settings are written into SpiderFoot's own config DB (which the
CLI reads) by a tiny helper that receives them on stdin, never on argv.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..config import SecretSpec, data_dir
from ..core import proc
from ..core.schema import Confidence, Finding, FindingType, TargetType
from .base import OptionSpec, RunContext, ToolAdapter, ToolError

# Fast, key-less modules. Deliberately excluded: sfp_accounts (checks ~500
# sites for every username found — that's Sherlock's job, offered as a
# related-finding pivot) and sfp_crt (crt.sh is slow and often times out).
QUICK_MODULES = (
    "sfp_dnsresolve", "sfp_dnsraw", "sfp_whois", "sfp_email", "sfp_pageinfo", "sfp_spider",
    "sfp_gravatar", "sfp_pgp", "sfp_sslcert", "sfp_webserver", "sfp_names",
    "sfp_phone", "sfp_social", "sfp_emailrep",
)

# secret key -> (SpiderFoot "module:option", label, env var)
KEYED_MODULES: dict[str, tuple[str, str, str]] = {
    "sf_shodan": ("sfp_shodan:api_key", "Shodan", "SF_SHODAN_API_KEY"),
    "sf_haveibeenpwned": ("sfp_haveibeenpwned:api_key", "Have I Been Pwned", "SF_HIBP_API_KEY"),
    "sf_hunter": ("sfp_hunter:api_key", "Hunter.io", "SF_HUNTER_API_KEY"),
    "sf_securitytrails": ("sfp_securitytrails:api_key", "SecurityTrails", "SF_SECURITYTRAILS_API_KEY"),
    "sf_virustotal": ("sfp_virustotal:api_key", "VirusTotal", "SF_VIRUSTOTAL_API_KEY"),
    "sf_ipinfo": ("sfp_ipinfo:api_key", "ipinfo.io", "SF_IPINFO_API_KEY"),
    "sf_emailrep": ("sfp_emailrep:api_key", "EmailRep", "SF_EMAILREP_API_KEY"),
}

_MODULES_RE = re.compile(r"^sfp_[a-z0-9_]+(?:,sfp_[a-z0-9_]+)*$")
_LOG_RE = re.compile(r"\[(ERROR|WARNING|CRITICAL)\]\s*(.*)$")

# SpiderFoot event *description* (what the CLI prints) -> (finding type, confidence)
EVENT_MAP: dict[str, tuple[FindingType, Confidence]] = {
    "Email Address": (FindingType.EMAIL, Confidence.MEDIUM),
    "Email Address - Generic": (FindingType.EMAIL, Confidence.MEDIUM),
    "Deliverable Email Address": (FindingType.EMAIL, Confidence.HIGH),
    "Hacked Email Address": (FindingType.EMAIL, Confidence.HIGH),
    "Affiliate - Email Address": (FindingType.EMAIL, Confidence.LOW),
    "Phone Number": (FindingType.PHONE, Confidence.MEDIUM),
    "Username": (FindingType.USERNAME, Confidence.MEDIUM),
    "Internet Name": (FindingType.DOMAIN, Confidence.HIGH),
    "Domain Name": (FindingType.DOMAIN, Confidence.HIGH),
    "Domain Name (Parent)": (FindingType.DOMAIN, Confidence.MEDIUM),
    "Co-Hosted Site": (FindingType.DOMAIN, Confidence.LOW),
    "Similar Domain": (FindingType.DOMAIN, Confidence.LOW),
    "Affiliate - Internet Name": (FindingType.DOMAIN, Confidence.LOW),
    "Affiliate - Domain Name": (FindingType.DOMAIN, Confidence.LOW),
    "IP Address": (FindingType.IP, Confidence.HIGH),
    "IPv6 Address": (FindingType.IP, Confidence.HIGH),
    "Affiliate - IP Address": (FindingType.IP, Confidence.LOW),
    "Affiliate - IPv6 Address": (FindingType.IP, Confidence.LOW),
    "Internet Name - Unresolved": (FindingType.DOMAIN, Confidence.LOW),
    "Account on External Site": (FindingType.ACCOUNT, Confidence.MEDIUM),
    "Hacked Account on External Site": (FindingType.ACCOUNT, Confidence.HIGH),
    "Similar Account on External Site": (FindingType.ACCOUNT, Confidence.LOW),
    "Social Media Presence": (FindingType.ACCOUNT, Confidence.MEDIUM),
    "Public Code Repository": (FindingType.ACCOUNT, Confidence.MEDIUM),
    "Linked URL - External": (FindingType.URL, Confidence.LOW),
    "Linked URL - Internal": (FindingType.URL, Confidence.MEDIUM),
    "Leak Site URL": (FindingType.URL, Confidence.MEDIUM),
    "Darknet Mention URL": (FindingType.URL, Confidence.LOW),
    "Physical Location": (FindingType.LOCATION, Confidence.MEDIUM),
    "Physical Address": (FindingType.LOCATION, Confidence.MEDIUM),
    "Country Name": (FindingType.LOCATION, Confidence.MEDIUM),
    "Physical Coordinates": (FindingType.GEO, Confidence.MEDIUM),
    "Human Name": (FindingType.PERSON, Confidence.LOW),
    "Company Name": (FindingType.PERSON, Confidence.LOW),
    "Job Title": (FindingType.PERSON, Confidence.LOW),
    "Telecommunications Provider": (FindingType.CARRIER, Confidence.MEDIUM),
    "Phone Number Type": (FindingType.CARRIER, Confidence.MEDIUM),
    "Software Used": (FindingType.SOFTWARE, Confidence.MEDIUM),
    "Web Technology": (FindingType.SOFTWARE, Confidence.MEDIUM),
    "Operating System": (FindingType.SOFTWARE, Confidence.LOW),
}

# Bulky or purely technical events: kept in raw output, not shown as findings.
SKIP_EVENTS = frozenset({
    "Raw DNS Records", "Raw Data from RIRs/APIs", "Domain Whois", "Affiliate - Domain Whois",
    "Co-Hosted Site - Domain Whois", "Similar Domain - Whois", "Netblock Whois", "Web Content",
    "Affiliate - Web Content", "HTTP Headers", "Raw File Meta Data", "SSL Certificate - Raw Data",
    "Search Engine Web Content", "Base64-encoded Data", "Junk File", "Error Message",
    "Web Content Type", "HTTP Status Code", "Cookies", "Non-Standard HTTP Header",
    "Darknet Mention Web Content", "Leak Site Content", "Internal SpiderFoot Root event",
    "PGP Public Key",
})


def parse_events(text: str) -> list[dict[str, Any]]:
    """Decode every JSON object in SpiderFoot's (not strictly valid) JSON stream."""
    dec = json.JSONDecoder()
    events: list[dict[str, Any]] = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        try:
            obj, end = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        if isinstance(obj, dict) and "type" in obj and "data" in obj:
            events.append(obj)
        i = end
    return events


class SpiderFootAdapter(ToolAdapter):
    name = "spiderfoot"
    title = "SpiderFoot"
    description = "Связи доменов, IP и аккаунтов"
    homepage = "https://github.com/smicallef/spiderfoot"
    input_types = frozenset({TargetType.DOMAIN, TargetType.IP, TargetType.EMAIL,
                             TargetType.PHONE, TargetType.USERNAME})
    default_timeout = 1800
    icon = "network"
    accent = "pink"
    order = 40
    secrets = tuple(SecretSpec(k, f"SpiderFoot · {label}", env, opt)
                    for k, (opt, label, env) in KEYED_MODULES.items())
    options = (
        OptionSpec("profile", "Набор модулей", "choice", "quick",
                   "Быстрый — 14 модулей без ключей (+ модули с заданными ключами)",
                   choices=(("quick", "Быстрый"), ("passive", "Пассивный (все пассивные)"),
                            ("footprint", "Цифровой след"), ("investigate", "Расследование"),
                            ("all", "Все модули (долго)"), ("custom", "Свой список"))),
        OptionSpec("modules", "Свой список модулей", "str", "",
                   "Через запятую: sfp_dnsresolve,sfp_whois,…"),
        OptionSpec("max_threads", "Потоков", "int", 4, minimum=1, maximum=32),
    )

    @property
    def root(self) -> Path:
        return self.tools_dir / "spiderfoot"

    @property
    def python(self) -> Path:
        return self.root / "python" / "python.exe"

    @property
    def sf_py(self) -> Path:
        return self.root / "spiderfoot" / "sf.py"

    def availability(self) -> tuple[bool, str]:
        if not self.python.exists():
            return False, f"нет встроенного Python ({self.python})"
        if not self.sf_py.exists():
            return False, f"нет {self.sf_py}"
        return True, ""

    def version(self) -> str | None:
        f = self.root / "VERSION"
        return f.read_text(encoding="utf-8").strip() if f.exists() else None

    def _env(self) -> dict[str, str]:
        sf_data = data_dir() / "spiderfoot"
        sf_data.mkdir(parents=True, exist_ok=True)
        # No .pyc writes: the install folder may be read-only (Program Files).
        return {"SPIDERFOOT_DATA": str(sf_data), "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def _keys(self) -> dict[str, str]:
        return {opt: self.secret(key) for key, (opt, _, _) in KEYED_MODULES.items()}

    def _modules(self, keys: dict[str, str]) -> list[str]:
        profile = self.option("profile")
        if profile == "custom":
            mods = (self.option("modules") or "").replace(" ", "")
            if not _MODULES_RE.match(mods):
                raise ToolError("SpiderFoot: некорректный список модулей в настройках")
            return ["-m", mods]
        if profile in ("passive", "footprint", "investigate", "all"):
            return ["-u", profile]
        mods = list(QUICK_MODULES) + [opt.split(":")[0] for opt, val in keys.items() if val]
        return ["-m", ",".join(dict.fromkeys(mods))]

    async def _push_keys(self, keys: dict[str, str], ctx: RunContext) -> None:
        # Only touch SpiderFoot's DB when the key set actually changed.
        fingerprint = hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()
        marker = self.work_dir / "keys.sha256"
        if marker.exists() and marker.read_text(encoding="utf-8") == fingerprint:
            return
        if not any(keys.values()) and not marker.exists():
            return
        helper = self.root / "osinthub_sf_config.py"
        if not helper.exists():
            ctx.log("SpiderFoot: нет osinthub_sf_config.py, API-ключи не применены", "warn")
            return
        res = await proc.run([self.python, helper], timeout=60, cwd=self.root, env=self._env(),
                             stdin_data=json.dumps(keys).encode("utf-8"))
        if res.returncode != 0:
            ctx.log(f"SpiderFoot: не удалось сохранить ключи: {res.stderr.strip()[-200:]}", "warn")
        else:
            marker.write_text(fingerprint, encoding="utf-8")

    async def run(self, target: str, ctx: RunContext) -> Any:
        sf_target = f'"{target}"' if ctx.target_type is TargetType.USERNAME else target
        keys = self._keys()
        await self._push_keys(keys, ctx)

        args = [str(self.python), "-X", "utf8", str(self.sf_py), "-s", sf_target, "-o", "json",
                "-max-threads", str(int(self.option("max_threads"))), *self._modules(keys)]
        events: list[dict[str, Any]] = []
        ctx.partial = {"events": events}

        def on_stdout(line: str) -> None:
            for ev in parse_events(line):
                events.append(ev)
                kind = ev.get("type", "")
                if kind in EVENT_MAP:
                    ctx.log(f"[FOUND] {kind}: {str(ev.get('data', ''))[:120]}", "found")
                ctx.progress(None, f"Событий: {len(events)}")

        def on_stderr(line: str) -> None:
            # SpiderFoot logs every unreachable site as ERROR; those are not fatal for the scan.
            if m := _LOG_RE.search(line):
                ctx.log(f"SpiderFoot: {m.group(2)[:300]}", "error" if m.group(1) == "CRITICAL" else "warn")
            elif "Scan completed" in line or "Modules enabled" in line:
                ctx.log(f"SpiderFoot: {line.split(' : ', 1)[-1][:300]}", "info")

        ctx.progress(None, "Запуск модулей")
        res = await proc.run(args, timeout=ctx.timeout, cwd=self.sf_py.parent, env=self._env(),
                             on_stdout=on_stdout, on_stderr=on_stderr)
        all_events = parse_events(res.stdout)
        if res.returncode != 0 and not all_events:
            tail = [l for l in res.stderr.strip().splitlines() if l.strip()]
            raise ToolError(f"SpiderFoot завершился с кодом {res.returncode}: {tail[-1][-300:] if tail else ''}")
        return {"events": all_events, "returncode": res.returncode}

    def parse_output(self, raw: Any) -> list[Finding]:
        events = (raw or {}).get("events", []) if isinstance(raw, dict) else parse_events(str(raw or ""))
        findings: list[Finding] = []
        for ev in events:
            kind = str(ev.get("type", ""))
            data = str(ev.get("data", "")).strip()
            module = str(ev.get("module", ""))
            if not data or kind in SKIP_EVENTS or module == "SpiderFoot UI":
                continue
            if kind.startswith(("URL (", "Historic URL")):
                continue
            ftype, conf = EVENT_MAP.get(kind, (FindingType.OTHER, Confidence.LOW))
            value = data if len(data) <= 500 else data[:500] + "…"
            extra: dict[str, Any] = {"field": kind, "module": module, "from": str(ev.get("source", ""))[:200]}
            if ftype is FindingType.ACCOUNT:
                # sfp_accounts / sfp_social emit "Site (Category)\n<SFURL>url</SFURL>"
                url = re.search(r"https?://\S+", data)
                if url:
                    extra["url"] = url.group(0).replace("</SFURL>", "")
                value = value.replace("<SFURL>", "").replace("</SFURL>", "").replace("\n", " ")
            if ftype is FindingType.URL:
                extra["url"] = data
            findings.append(Finding(ftype.value, value, f"SpiderFoot · {module.removeprefix('sfp_')}",
                                    conf.value, extra))
        return findings
