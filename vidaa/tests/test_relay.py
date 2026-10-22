import unittest
import urllib.error
import urllib.request

from detox.relay import Relay, serve
from detox.tv import TVError

TILES = [{"id": "netflix", "name": "Netflix", "kind": "app", "app": "Netflix"},
         {"id": "console", "name": {"ro": "Consolă", "en": "Console"}, "kind": "source", "source": "HDMI1"}]


class FakeTV:
    def __init__(self):
        self.calls = []

    def launch(self, name):
        if name == "Missing":
            raise TVError("no app called Missing")
        self.calls.append(("launch", name))

    def change_source(self, name):
        self.calls.append(("source", name))

    def open_url(self, app_id, name, url):
        self.calls.append(("open", app_id, url))

    def send_key(self, key):
        self.calls.append(("key", key))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def relay(tv=None, auto_home=True, clock=None):
    return Relay(tv or FakeTV(), TILES, token="tok123", home_id="calmhome",
                 home_url="https://alextudose.github.io/tv-detox/", self_url="http://192.168.1.129:8788/tok123",
                 auto_home=auto_home, clock=clock or Clock())


class LaunchRouteTest(unittest.TestCase):
    def test_launches_the_native_app_named_in_the_tile(self):
        r = relay()

        status, body = r.handle("/tok123/launch/netflix")

        self.assertEqual(status, 200)
        self.assertEqual(r.tv.calls, [("launch", "Netflix")])
        self.assertIn("Netflix", body)

    def test_an_input_tile_switches_the_source(self):
        r = relay()

        r.handle("/tok123/launch/console")

        self.assertEqual(r.tv.calls, [("source", "HDMI1")])

    def test_a_wrong_token_touches_nothing(self):
        r = relay()

        self.assertEqual(r.handle("/guess/launch/netflix")[0], 404)
        self.assertEqual(r.tv.calls, [])

    def test_an_unknown_tile_is_not_found(self):
        self.assertEqual(relay().handle("/tok123/launch/nope")[0], 404)

    def test_a_failed_launch_sends_the_user_back_home(self):
        r = Relay(FakeTV(), [{"id": "x", "name": "X", "kind": "app", "app": "Missing"}], "tok123", "calmhome",
                  "https://h/", "http://192.168.1.129:8788/tok123", False, Clock())

        status, body = r.handle("/tok123/launch/x")

        self.assertEqual(status, 502)
        self.assertIn("history.back", body)


class AutoHomeTest(unittest.TestCase):
    def test_reopens_the_calm_home_with_the_relay_address_when_vidaa_home_shows(self):
        r = relay()

        r.on_state({"statetype": "remote_launcher"})

        self.assertEqual(r.tv.calls, [("open", "calmhome",
                                       "https://alextudose.github.io/tv-detox/#relay=http://192.168.1.129:8788/tok123")])

    def test_does_nothing_while_an_app_is_open_or_when_switched_off(self):
        r = relay()
        r.on_state({"statetype": "app", "name": "netflix"})
        off = relay(auto_home=False)
        off.on_state({"statetype": "remote_launcher"})

        self.assertEqual(r.tv.calls + off.tv.calls, [])

    def test_does_not_loop_right_after_its_own_launch(self):
        clock = Clock()
        r = relay(clock=clock)
        r.on_state({"statetype": "remote_launcher"})
        clock.t += 3
        r.on_state({"statetype": "remote_launcher"})
        clock.t += 10
        r.on_state({"statetype": "remote_launcher"})

        self.assertEqual(len(r.tv.calls), 2)

    def test_classic_pauses_auto_home_for_ten_minutes_and_shows_vidaa_home(self):
        clock = Clock()
        r = relay(clock=clock)

        status, _ = r.handle("/tok123/classic")
        r.on_state({"statetype": "remote_launcher"})
        clock.t += 601
        r.on_state({"statetype": "remote_launcher"})

        self.assertEqual(status, 200)
        self.assertEqual(r.tv.calls[0], ("key", "KEY_HOME"))
        self.assertEqual([c[0] for c in r.tv.calls], ["key", "open"])


class HttpTest(unittest.TestCase):
    def test_serves_the_routes_over_http(self):
        r = relay()
        server = serve(r, "127.0.0.1", 0)
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + "/tok123/launch/netflix", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/nope", timeout=5)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(r.tv.calls, [("launch", "Netflix")])
