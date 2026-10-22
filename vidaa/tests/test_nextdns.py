import unittest

from detox.nextdns import NextDNS, NextDNSError, plan_batch


class FakeApi:
    """Answers like api.nextdns.io (shapes from nextdns.github.io/api)."""

    def __init__(self, pages=None, post_errors=None):
        self.calls = []
        self.pages = pages or [[]]
        self.post_errors = post_errors

    def __call__(self, method, path, body=None, params=None):
        self.calls.append((method, path, body, params))
        if method == "GET" and path.endswith("/logs"):
            index = int((params or {}).get("cursor") or 0)
            cursor = str(index + 1) if index + 1 < len(self.pages) else None
            return {"data": self.pages[index], "meta": {"pagination": {"cursor": cursor}}}
        if method == "GET" and path.endswith("/denylist"):
            return {"data": [{"id": "already.vidaahub.com", "active": True}]}
        if method == "GET":
            return {"data": {"name": "TV", "denylist": [], "allowlist": []}}
        if method == "POST" and self.post_errors:
            return {"errors": self.post_errors}
        return {}


def entry(domain, status="default"):
    return {"timestamp": "2026-10-22T10:00:00.000Z", "domain": domain, "root": domain.split(".", 1)[-1],
            "status": status, "reasons": [], "device": None}


class ClientTest(unittest.TestCase):
    def test_blocking_posts_an_active_denylist_entry_for_exactly_that_host(self):
        api = FakeApi()

        NextDNS("abc123", http=api).deny("rpt-ads.vidaahub.com")

        self.assertEqual(api.calls, [("POST", "/profiles/abc123/denylist",
                                      {"id": "rpt-ads.vidaahub.com", "active": True}, None)])

    def test_an_error_inside_a_200_response_is_still_an_error(self):
        api = FakeApi(post_errors=[{"code": "invalid", "detail": "invalid domain", "source": {"pointer": "/id"}}])

        with self.assertRaises(NextDNSError) as raised:
            NextDNS("abc123", http=api).deny("not a domain")

        self.assertIn("invalid domain", str(raised.exception))

    def test_unblocking_deletes_the_denylist_child(self):
        api = FakeApi()

        NextDNS("abc123", http=api).undeny("rpt-ads.vidaahub.com")

        self.assertEqual(api.calls[0][:2], ("DELETE", "/profiles/abc123/denylist/rpt-ads.vidaahub.com"))

    def test_domain_counts_follow_every_log_page(self):
        api = FakeApi(pages=[[entry("rpt-ads.vidaahub.com"), entry("ota-tv.vidaahub.com")],
                             [entry("rpt-ads.vidaahub.com", "blocked")]])

        counts = NextDNS("abc123", http=api).domain_counts(since="-2h")

        self.assertEqual(counts["rpt-ads.vidaahub.com"], {"queries": 2, "blocked": 1})
        self.assertEqual(counts["ota-tv.vidaahub.com"], {"queries": 1, "blocked": 0})
        self.assertEqual([c[3].get("cursor") for c in api.calls], [None, "1"])

    def test_profile_backup_returns_the_profile_data(self):
        self.assertEqual(NextDNS("abc123", http=FakeApi()).profile()["name"], "TV")


class PlanBatchTest(unittest.TestCase):
    CANDIDATES = ("rpt-ads.vidaahub.com", "api-logsdk.hismarttv.com", "recommend-ui.vidaahub.com",
                  "acr.unruly.co", "ota-tv.vidaahub.com")
    ALLOW = ("ota-tv.vidaahub.com",)

    def test_blocks_only_candidates_the_tv_actually_queried_busiest_first(self):
        seen = {"recommend-ui.vidaahub.com": {"queries": 5, "blocked": 0},
                "rpt-ads.vidaahub.com": {"queries": 40, "blocked": 0},
                "netflix.com": {"queries": 90, "blocked": 0}}

        batch = plan_batch(seen, self.CANDIDATES, self.ALLOW, already=[], size=10)

        self.assertEqual(batch, ["rpt-ads.vidaahub.com", "recommend-ui.vidaahub.com"])

    def test_never_blocks_an_allowlisted_host_even_if_it_is_a_candidate(self):
        seen = {"ota-tv.vidaahub.com": {"queries": 99, "blocked": 0}}

        self.assertEqual(plan_batch(seen, self.CANDIDATES, self.ALLOW, already=[], size=10), [])

    def test_skips_hosts_already_blocked_and_caps_the_batch(self):
        seen = {d: {"queries": 10 - i, "blocked": 0} for i, d in enumerate(self.CANDIDATES)}

        batch = plan_batch(seen, self.CANDIDATES, self.ALLOW, already=["rpt-ads.vidaahub.com"], size=2)

        self.assertEqual(batch, ["api-logsdk.hismarttv.com", "recommend-ui.vidaahub.com"])


import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from detox import nextdns


class LocalApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("X-Api-Key") != "k3y":
            return self._reply(401, {"errors": [{"code": "unauthorized"}]})
        self._reply(200, {"data": {"name": "TV", "seen": self.path}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._reply(200, {"errors": [{"code": "invalid", "detail": f"bad {body['id']}"}]} if " " in body["id"] else {})


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalApi)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_sends_the_api_key_and_query_parameters(self):
        client = NextDNS("abc123", http=nextdns._http("k3y", base=self.base))

        self.assertEqual(client.profile()["seen"], "/profiles/abc123")
        self.assertEqual(client._call("GET", "/logs", params={"from": "-2h"})["data"]["seen"],
                         "/profiles/abc123/logs?from=-2h")

    def test_a_wrong_key_is_an_error_with_the_reason(self):
        with self.assertRaises(NextDNSError) as raised:
            NextDNS("abc123", http=nextdns._http("wrong", base=self.base)).profile()
        self.assertIn("unauthorized", str(raised.exception))

    def test_user_errors_in_a_200_are_raised(self):
        with self.assertRaises(NextDNSError):
            NextDNS("abc123", http=nextdns._http("k3y", base=self.base)).deny("not a domain")


class KeychainTest(unittest.TestCase):
    def test_reads_the_key_from_the_keychain_item(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "s3cret\n", "")

        self.assertEqual(nextdns.keychain_key(run=run), "s3cret")
        self.assertIn("vidaa-detox-nextdns", calls[0])

    def test_a_missing_key_explains_where_it_should_be(self):
        run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 44, "", "could not be found")

        with self.assertRaises(NextDNSError) as raised:
            nextdns.keychain_key(run=run)
        self.assertIn("Keychain", str(raised.exception))
