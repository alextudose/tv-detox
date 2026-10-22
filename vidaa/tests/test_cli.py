import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import ClassVar

from detox.cli import Deps, main
from detox.tv import TV

from tests.fake_tv import MOBILE, FakeTVSession, runner_for
from tests.test_tv import APPS, SOURCES

RENDERER = "<root><device><friendlyName>Default Room</friendlyName></device></root>"
TV_DATE = "Thu, 22 Oct 2026 08:40:34 GMT"


class FakeCamera:
    def __init__(self):
        self.shots = []

    def capture(self, out):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff\xd8")
        self.shots.append(out)
        return out


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.session_file = root / "sidee" / "session.json"
        self.session_file.parent.mkdir()
        self.session_file.write_text('{"access_token": "secret"}')
        self.session = FakeTVSession({
            "actions/gettvstate": [("/remoteapp/mobile/broadcast/ui_service/state",
                                    '{"statetype": "remote_launcher"}')],
            "actions/applist": [(MOBILE + "ui_service/data/applist", json.dumps(APPS))],
            "actions/sourcelist": [(MOBILE + "ui_service/data/sourcelist", json.dumps(SOURCES))],
            "actions/gettvinfo": [(MOBILE + "platform_service/data/gettvinfo", '{"model_name": "55A5HE"}')],
        })
        self.camera = FakeCamera()
        self.deps = Deps(
            tv=lambda host: TV(host, runner=runner_for(self.session), wait=0),
            camera=self.camera,
            fetch=lambda url: (RENDERER, TV_DATE),
            now=lambda: 1792658434.0,  # 2026-10-22 08:40:34 UTC, same second as the TV
            session_path=self.session_file,
            runs=root / "runs",
            host="192.168.1.132",
        )

    def tearDown(self):
        self.dir.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv), self.deps)
        return code, out.getvalue(), err.getvalue()

    def current_run(self):
        return self.deps.runs / (self.deps.runs / "CURRENT").read_text().strip()


class CliTest(CliFixture):
    def test_two_backups_in_the_same_second_get_separate_runs(self):
        self.run_cli("backup")
        first = self.current_run()

        self.assertEqual(self.run_cli("backup")[0], 0)

        self.assertNotEqual(self.current_run(), first)

    def test_backup_snapshots_everything_the_detox_can_change(self):
        code, _, _ = self.run_cli("backup")

        self.assertEqual(code, 0)
        backup = self.current_run() / "backup"
        self.assertEqual(json.loads((backup / "applist.json").read_text()), APPS)
        self.assertEqual(json.loads((backup / "sourcelist.json").read_text()), SOURCES)
        self.assertEqual(json.loads((backup / "state.json").read_text())["statetype"], "remote_launcher")
        self.assertEqual(json.loads((backup / "info.json").read_text())["tvinfo"]["model_name"], "55A5HE")
        self.assertEqual((backup / "renderer.xml").read_text(), RENDERER)

    def test_backup_keeps_the_pairing_token_private(self):
        self.run_cli("backup")

        copy = self.current_run() / "backup" / "session.json"
        self.assertEqual(copy.read_text(), '{"access_token": "secret"}')
        self.assertEqual(stat.S_IMODE(os.stat(copy).st_mode), 0o600)

    def test_shots_are_numbered_and_journalled_with_the_tv_state(self):
        self.run_cli("backup")

        self.run_cli("shot", "home before")
        self.run_cli("shot", "settings")

        shots = sorted(p.name for p in (self.current_run() / "shots").iterdir())
        self.assertEqual(shots, ["01-home-before.jpg", "02-settings.jpg"])
        journal = (self.current_run() / "journal.md").read_text()
        self.assertIn("01-home-before.jpg", journal)
        self.assertIn("remote_launcher", journal)

    def test_a_shot_still_saves_when_the_tv_is_silent(self):
        self.session.replies.pop("actions/gettvstate")

        code, _, _ = self.run_cli("shot", "tv off")

        self.assertEqual(code, 0)
        self.assertIn("no state", (self.current_run() / "journal.md").read_text())

    def test_clock_skew_beyond_a_minute_stops_before_any_login(self):
        self.deps.now = lambda: 1792658434.0 + 90

        code, _, err = self.run_cli("skew")

        self.assertEqual(code, 2)
        self.assertIn("90", err)

    def test_clock_in_sync_passes(self):
        code, out, _ = self.run_cli("skew")

        self.assertEqual(code, 0)
        self.assertIn("0 s", out)

    def test_launch_by_name_and_unknown_app_exit_codes(self):
        self.assertEqual(self.run_cli("launch", "netflix")[0], 0)

        code, _, err = self.run_cli("launch", "stremio")

        self.assertEqual(code, 1)
        self.assertIn("Netflix", err)

    def test_state_prints_json(self):
        code, out, _ = self.run_cli("state")

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["statetype"], "remote_launcher")


class PairTest(CliFixture):
    def test_pairing_reads_the_pin_from_a_file_written_while_it_waits(self):
        pin_file = Path(self.dir.name) / "PIN"
        seen = {}

        def fake_pair(host, pin_provider):
            pin_file.write_text("4821\n")  # the user reads it off the TV and it gets written meanwhile
            seen["host"], seen["pin"] = host, pin_provider()
            return type("Session", (), {"auth_profile": "modern"})()

        self.deps.pair = fake_pair
        code, out, _ = self.run_cli("pair", "--pin-file", str(pin_file))

        self.assertEqual(code, 0)
        self.assertEqual(seen, {"host": "192.168.1.132", "pin": "4821"})
        self.assertFalse(pin_file.exists(), "the PIN file is single-use")
        self.assertIn("modern", out)

    def test_pairing_refuses_to_start_when_the_clocks_disagree(self):
        self.deps.now = lambda: 1792658434.0 + 300
        self.deps.pair = lambda host, pin_provider: self.fail("must not try to log in")

        self.assertEqual(self.run_cli("pair")[0], 2)


class SpeedTest(CliFixture):
    def test_speed_records_median_launch_and_home_times_per_app(self):
        self.session.replies["actions/launchapp"] = [(
            "/remoteapp/mobile/broadcast/ui_service/state",
            '{"statetype": "app", "name": "netflix", "appId": "1"}')]
        self.session.replies["actions/sendkey"] = [(
            "/remoteapp/mobile/broadcast/ui_service/state", '{"statetype": "remote_launcher"}')]

        code, _, _ = self.run_cli("speed", "before", "--apps", "Netflix", "--rounds", "3", "--settle", "0")

        self.assertEqual(code, 0)
        result = json.loads((self.current_run() / "speed-before.json").read_text())
        self.assertEqual(len(result["Netflix"]["launch_s"]), 3)
        self.assertIn("median_launch_s", result["Netflix"])
        self.assertIn("median_home_s", result["Netflix"])

    def test_an_app_that_never_opens_is_recorded_as_a_timeout(self):
        self.session.replies["actions/sendkey"] = [(
            "/remoteapp/mobile/broadcast/ui_service/state", '{"statetype": "remote_launcher"}')]

        self.run_cli("speed", "before", "--apps", "Netflix", "--rounds", "1", "--timeout", "0.2", "--settle", "0")

        result = json.loads((self.current_run() / "speed-before.json").read_text())
        self.assertEqual(result["Netflix"]["launch_s"], [None])


class FakeDNS:
    def __init__(self, seen=None, fail_on=None):
        self.seen = seen or {}
        self.fail_on = fail_on
        self.denied, self.undenied = [], []

    def profile(self):
        return {"name": "TV", "denylist": []}

    def domain_counts(self, since="-24h"):
        return self.seen

    def denylist(self):
        return [{"id": d, "active": True} for d in self.denied]

    def deny(self, domain):
        from detox.nextdns import NextDNSError
        if domain == self.fail_on:
            raise NextDNSError("invalid domain")
        self.denied.append(domain)

    def undeny(self, domain):
        self.undenied.append(domain)


class DnsTest(CliFixture):
    SEEN: ClassVar[dict] = {"rpt-ads.vidaahub.com": {"queries": 30, "blocked": 0},
            "api-logsdk.hismarttv.com": {"queries": 12, "blocked": 0},
            "ota-tv.vidaahub.com": {"queries": 50, "blocked": 0},
            "nflxvideo.net": {"queries": 400, "blocked": 0}}

    def setUp(self):
        super().setUp()
        self.dns = FakeDNS(self.SEEN)
        self.deps.dns = lambda: self.dns
        self.run_cli("backup")

    def manifest(self):
        from detox.manifest import Manifest
        return Manifest(self.current_run() / "manifest.json")

    def test_backup_saves_the_profile_before_any_change(self):
        self.assertEqual(self.run_cli("dns", "backup")[0], 0)

        saved = json.loads((self.current_run() / "backup" / "nextdns-profile.json").read_text())
        self.assertEqual(saved["name"], "TV")

    def test_observe_lists_what_the_tv_queried_and_marks_candidates(self):
        code, out, _ = self.run_cli("dns", "observe")

        self.assertEqual(code, 0)
        self.assertIn("rpt-ads.vidaahub.com", out)
        self.assertIn("candidate", out)
        self.assertIn("never block", out)  # ota-tv is allowlisted
        self.assertTrue((self.current_run() / "dns-observed.json").exists())

    def test_block_without_yes_only_shows_the_plan(self):
        code, out, _ = self.run_cli("dns", "block")

        self.assertEqual(code, 0)
        self.assertIn("rpt-ads.vidaahub.com", out)
        self.assertEqual(self.dns.denied, [])
        self.assertEqual(self.manifest().entries(), [])

    def test_block_with_yes_journals_then_blocks_seen_candidates_only(self):
        code, _, _ = self.run_cli("dns", "block", "--yes")

        self.assertEqual(code, 0)
        self.assertEqual(self.dns.denied, ["rpt-ads.vidaahub.com", "api-logsdk.hismarttv.com"])
        entries = self.manifest().entries()
        self.assertEqual([(e["kind"], e["target"], e["status"]) for e in entries],
                         [("dns-deny", "rpt-ads.vidaahub.com", "applied"),
                          ("dns-deny", "api-logsdk.hismarttv.com", "applied")])

    def test_a_failed_block_is_journalled_and_stops_the_batch(self):
        self.dns.fail_on = "rpt-ads.vidaahub.com"

        code, _, _ = self.run_cli("dns", "block", "--yes")

        self.assertEqual(code, 1)
        self.assertEqual(self.dns.denied, [])
        self.assertEqual([e["status"] for e in self.manifest().entries()], ["failed"])

    def test_unblock_ours_reverses_only_what_we_added_newest_first(self):
        self.run_cli("dns", "block", "--yes")

        code, _, _ = self.run_cli("dns", "unblock", "--ours")

        self.assertEqual(code, 0)
        self.assertEqual(self.dns.undenied, ["api-logsdk.hismarttv.com", "rpt-ads.vidaahub.com"])
        self.assertTrue(all(e["status"] == "reverted" for e in self.manifest().entries()))


class HomeAndRelayTest(CliFixture):
    def setUp(self):
        super().setUp()
        self.tiles_added, self.launchctl_calls = [], []
        self.deps.add_tile = lambda app_id, name, url, image: self.tiles_added.append((app_id, name, url, image))
        self.deps.launchctl = lambda args: self.launchctl_calls.append(args)
        self.deps.agents = Path(self.dir.name) / "LaunchAgents"
        self.run_cli("backup")

    def manifest(self):
        from detox.manifest import Manifest
        return Manifest(self.current_run() / "manifest.json").entries()

    def test_home_install_journals_then_registers_the_tile(self):
        code, _, _ = self.run_cli("home", "install", "--url", "https://alextudose.github.io/tv-detox/")

        self.assertEqual(code, 0)
        self.assertEqual(self.tiles_added, [("calmhome", "Acasă", "https://alextudose.github.io/tv-detox/",
                                             "https://alextudose.github.io/tv-detox/icon.png")])
        self.assertEqual([(e["kind"], e["target"], e["status"]) for e in self.manifest()],
                         [("tile", "calmhome", "applied")])
        self.assertEqual((self.deps.runs / "home-url").read_text(), "https://alextudose.github.io/tv-detox/")

    def test_home_install_refuses_a_non_https_address(self):
        code, _, _ = self.run_cli("home", "install", "--url", "http://example.com/")

        self.assertEqual(code, 1)
        self.assertEqual(self.tiles_added, [])

    def test_relay_install_writes_a_launch_agent_and_loads_it(self):
        (self.deps.runs / "home-url").write_text("https://alextudose.github.io/tv-detox/")

        code, _, _ = self.run_cli("relay", "install", "--auto-home")

        self.assertEqual(code, 0)
        plist = (self.deps.agents / "io.github.alextudose.tvdetox.relay.plist").read_text()
        self.assertIn("<string>relay</string>", plist)
        self.assertIn("<string>--auto-home</string>", plist)
        self.assertEqual(self.launchctl_calls[-1][0], "bootstrap")
        self.assertEqual([e["kind"] for e in self.manifest()], ["relay"])
        token = (self.deps.runs / "relay-token").read_text()
        self.assertGreaterEqual(len(token), 16)
        self.assertEqual(oct(os.stat(self.deps.runs / "relay-token").st_mode & 0o777), "0o600")

    def test_relay_needs_the_home_installed_first(self):
        self.assertEqual(self.run_cli("relay", "install")[0], 1)
        self.assertEqual(self.launchctl_calls, [])

    def test_relay_uninstall_unloads_and_removes_the_agent(self):
        (self.deps.runs / "home-url").write_text("https://alextudose.github.io/tv-detox/")
        self.run_cli("relay", "install")

        code, _, _ = self.run_cli("relay", "uninstall")

        self.assertEqual(code, 0)
        self.assertEqual(self.launchctl_calls[-1][0], "bootout")
        self.assertFalse((self.deps.agents / "io.github.alextudose.tvdetox.relay.plist").exists())
        self.assertEqual([e["status"] for e in self.manifest()], ["reverted"])


class RestoreTest(CliFixture):
    def setUp(self):
        super().setUp()
        from detox.manifest import Manifest
        self.dns = FakeDNS()
        self.deps.dns = lambda: self.dns
        self.launchctl_calls = []
        self.deps.launchctl = lambda args: self.launchctl_calls.append(args)
        self.deps.agents = Path(self.dir.name) / "LaunchAgents"
        self.answers = []
        self.deps.ask = lambda prompt: self.answers.pop(0) if self.answers else "n"
        old = self.deps.runs / "20261022-092859"
        old.mkdir(parents=True)
        m_old = Manifest(old / "manifest.json")
        menu = m_old.record(kind="menu", target="ACR", before="On", after="Off", undo="Settings > ACR: On")
        m_old.mark(menu, "applied")
        new = self.deps.runs / "20261022-120000"
        new.mkdir()
        (self.deps.runs / "CURRENT").write_text(new.name)
        m_new = Manifest(new / "manifest.json")
        for kind, target in (("dns-deny", "rpt-ads.vidaahub.com"), ("relay", "io.github.alextudose.tvdetox.relay")):
            m_new.mark(m_new.record(kind=kind, target=target, before=None, after="x", undo="..."), "applied")
        self.old, self.new = Manifest(old / "manifest.json"), Manifest(new / "manifest.json")

    def test_dry_run_lists_every_run_newest_first_and_changes_nothing(self):
        code, out, _ = self.run_cli("restore", "--dry-run")

        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.startswith("- ")]
        self.assertEqual([l.split()[1] for l in lines], ["relay", "dns-deny", "menu"])
        self.assertEqual(self.dns.undenied, [])
        self.assertEqual(self.launchctl_calls, [])

    def test_restore_undoes_automated_steps_and_guides_the_menu_one(self):
        self.answers = ["y"]

        code, out, _ = self.run_cli("restore")

        self.assertEqual(code, 0)
        self.assertEqual(self.launchctl_calls[0][0], "bootout")
        self.assertEqual(self.dns.undenied, ["rpt-ads.vidaahub.com"])
        self.assertIn("Settings > ACR: On", out)
        self.assertTrue(all(e["status"] == "reverted" for e in self.old.entries() + self.new.entries()))

    def test_a_skipped_guided_step_stays_open_and_fails_the_restore(self):
        code, _, err = self.run_cli("restore")

        self.assertEqual(code, 1)
        self.assertEqual(self.old.entries()[0]["status"], "applied")
        self.assertIn("1 step", err)

    def test_only_limits_the_restore_to_one_kind(self):
        code, _, _ = self.run_cli("restore", "--only", "dns")

        self.assertEqual(code, 0)
        self.assertEqual(self.dns.undenied, ["rpt-ads.vidaahub.com"])
        self.assertEqual(self.launchctl_calls, [])

    def test_a_tile_counts_as_removed_only_when_the_tv_no_longer_lists_it(self):
        from detox.manifest import Manifest
        m = Manifest(self.deps.runs / "20261022-120000" / "manifest.json")
        m.mark(m.record(kind="tile", target="1", before="absent", after="url", undo="remove it"), "applied")
        self.answers = ["y"]  # Netflix (appId 1) is still in the fake TV's app list

        code, _, _ = self.run_cli("restore", "--only", "home")

        self.assertEqual(code, 1)
        self.assertEqual([e["status"] for e in m.entries() if e["kind"] == "tile"], ["applied"])
