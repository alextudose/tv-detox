"""NextDNS profile for the TV: what it queries (logs), and a denylist we add
to in small, reversible batches. API: https://nextdns.github.io/api/"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://api.nextdns.io"
KEYCHAIN_SERVICE = "vidaa-detox-nextdns"


class NextDNSError(Exception):
    pass


def keychain_key(run=subprocess.run) -> str:
    result = run(["security", "find-generic-password", "-a", os.environ.get("USER", ""),
                  "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise NextDNSError(f"no NextDNS API key in the Keychain (service {KEYCHAIN_SERVICE})")
    return result.stdout.strip()


def _http(key: str, base: str = API):
    def call(method: str, path: str, body=None, params=None) -> dict:
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"X-Api-Key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            if not raw:
                raise NextDNSError(f"{method} {path}: HTTP {e.code}") from e
        return json.loads(raw) if raw.strip() else {}
    return call


class NextDNS:
    def __init__(self, profile: str, key: str | None = None, http=None):
        self.profile_id = profile
        self.http = http or _http(key or keychain_key())

    def _call(self, method: str, path: str, body=None, params=None) -> dict:
        reply = self.http(method, f"/profiles/{self.profile_id}{path}", body, params)
        if reply.get("errors"):  # NextDNS reports user errors inside 200 responses too
            details = "; ".join(e.get("detail") or e.get("code", "?") for e in reply["errors"])
            raise NextDNSError(f"{method} {path}: {details}")
        return reply

    def profile(self) -> dict:
        return self._call("GET", "")["data"]

    def denylist(self) -> list[dict]:
        return self._call("GET", "/denylist")["data"]

    def deny(self, domain: str) -> None:
        self._call("POST", "/denylist", {"id": domain, "active": True})

    def undeny(self, domain: str) -> None:
        self._call("DELETE", f"/denylist/{urllib.parse.quote(domain)}")

    def domain_counts(self, since: str = "-24h") -> dict[str, dict]:
        counts: dict[str, dict] = defaultdict(lambda: {"queries": 0, "blocked": 0})
        cursor = None
        while True:
            params = {"from": since, "limit": 1000, **({"cursor": cursor} if cursor else {})}
            page = self._call("GET", "/logs", params=params)
            for item in page["data"]:
                counts[item["domain"]]["queries"] += 1
                counts[item["domain"]]["blocked"] += item.get("status") == "blocked"
            cursor = page.get("meta", {}).get("pagination", {}).get("cursor")
            if not cursor:
                return dict(counts)


def plan_batch(seen: dict[str, dict], candidates: list[str], allow: list[str],
               already: list[str], size: int = 10) -> list[str]:
    """Next hosts to block: candidates the TV really queried, never an
    allowlisted or already-blocked one, busiest first."""
    wanted = [d for d in candidates if d in seen and d not in allow and d not in already]
    return sorted(wanted, key=lambda d: -seen[d]["queries"])[:size]
