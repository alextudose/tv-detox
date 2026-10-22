import json
import unittest

from detox.tv import TV, TVError

from tests.fake_tv import MOBILE, FakeTVSession, runner_for

BROADCAST_STATE = "/remoteapp/mobile/broadcast/ui_service/state"


class StateTest(unittest.TestCase):
    def test_reports_the_home_screen_state_broadcast_by_the_tv(self):
        session = FakeTVSession({"actions/gettvstate": [
            (BROADCAST_STATE, json.dumps({"statetype": "remote_launcher"}))]})

        state = TV(runner=runner_for(session), wait=0).state()

        self.assertEqual(state, {"statetype": "remote_launcher"})

    def test_accepts_state_addressed_directly_to_this_client(self):
        session = FakeTVSession({"actions/gettvstate": [
            (MOBILE + "ui_service/data/state", json.dumps({"statetype": "app", "name": "Netflix"}))]})

        state = TV(runner=runner_for(session), wait=0).state()

        self.assertEqual(state["name"], "Netflix")

    def test_silence_from_the_tv_is_an_error_not_an_empty_state(self):
        session = FakeTVSession()

        with self.assertRaises(TVError):
            TV(runner=runner_for(session), wait=0).state()


APPS = [
    {"appId": "1", "name": "Netflix", "url": "netflix", "storeType": 0},
    {"appId": "2", "name": "Prime Video", "url": "amazon", "storeType": 0},
    {"appId": "3", "name": "YouTube", "url": "youtube", "storeType": 0},
]
SOURCES = [
    {"sourceid": "0", "sourcename": "TV", "displayname": "TV"},
    {"sourceid": "3", "sourcename": "HDMI1", "displayname": "PlayStation"},
    {"sourceid": "4", "sourcename": "HDMI2", "displayname": "HDMI 2"},
]


def tv_with(**replies):
    session = FakeTVSession({
        "actions/applist": [(MOBILE + "ui_service/data/applist", json.dumps(APPS))],
        "actions/sourcelist": [(MOBILE + "ui_service/data/sourcelist", json.dumps(SOURCES))],
        **replies})
    return TV(runner=runner_for(session), wait=0), session


def published(session, suffix):
    return [json.loads(p) if p[:1] in "{[" else p for t, p in session.published if t.endswith(suffix)]


class LaunchTest(unittest.TestCase):
    def test_launches_an_installed_app_by_name_with_the_tvs_own_record(self):
        tv, session = tv_with()

        tv.launch("netflix")

        self.assertEqual(published(session, "ui_service/" + session.client_id + "/actions/launchapp"),
                         [{"appId": "1", "name": "Netflix", "url": "netflix"}])

    def test_name_match_is_a_case_insensitive_prefix(self):
        tv, session = tv_with()

        tv.launch("prime")

        self.assertEqual(published(session, "actions/launchapp")[0]["url"], "amazon")

    def test_an_app_the_tv_does_not_have_is_an_error_naming_what_it_has(self):
        tv, _ = tv_with()

        with self.assertRaises(TVError) as raised:
            tv.launch("Stremio")

        self.assertIn("Netflix", str(raised.exception))

    def test_opens_a_web_page_as_an_app_without_installing_a_tile(self):
        tv, session = tv_with()

        tv.open_url("detoxprobe", "Detox probe", "http://192.168.1.129:8787/probe.html")

        payload = published(session, "actions/launchapp")[0]
        self.assertEqual(payload["url"], "http://192.168.1.129:8787/probe.html")
        self.assertEqual(payload["urlType"], 37)
        self.assertEqual(published(session, "actions/uievent"), [])


class RemoteKeyTest(unittest.TestCase):
    def test_sends_a_remote_key_on_the_remote_service(self):
        tv, session = tv_with()

        tv.send_key("KEY_HOME")

        self.assertEqual(session.published,
                         [(f"/remoteapp/tv/remote_service/{session.client_id}/actions/sendkey", "KEY_HOME")])

    def test_refuses_anything_that_is_not_a_key_name(self):
        tv, session = tv_with()

        for bad in ("HOME", "KEY_home; rm", ""):
            with self.assertRaises(ValueError):
                tv.send_key(bad)
        self.assertEqual(session.published, [])


class SourceTest(unittest.TestCase):
    def test_switches_to_an_input_by_its_name_or_label(self):
        tv, session = tv_with()

        tv.change_source("playstation")

        self.assertEqual(published(session, "actions/changesource"),
                         [{"sourceid": "3", "sourcename": "HDMI1"}])

    def test_unknown_input_is_an_error(self):
        tv, _ = tv_with()

        with self.assertRaises(TVError):
            tv.change_source("hdmi9")


class InfoTest(unittest.TestCase):
    def test_collects_tv_device_and_capability_info(self):
        tv, _ = tv_with(**{
            "actions/gettvinfo": [(MOBILE + "platform_service/data/gettvinfo", '{"model_name": "55A5HE"}')],
            "actions/getdeviceinfo": [(MOBILE + "platform_service/data/getdeviceinfo", '{"tv_version": "V0000.09"}')],
            "actions/capability": [(MOBILE + "ui_service/data/capability", '{"support_applist": 1}')],
        })

        info = tv.info()

        self.assertEqual(info["tvinfo"]["model_name"], "55A5HE")
        self.assertEqual(info["deviceinfo"]["tv_version"], "V0000.09")
        self.assertEqual(info["capability"]["support_applist"], 1)

    def test_info_keeps_what_answered_when_one_part_is_silent(self):
        tv, _ = tv_with(**{
            "actions/gettvinfo": [(MOBILE + "platform_service/data/gettvinfo", '{"model_name": "55A5HE"}')]})

        info = tv.info()

        self.assertEqual(info["tvinfo"]["model_name"], "55A5HE")
        self.assertIsNone(info["deviceinfo"])


class WatchTest(unittest.TestCase):
    def test_reports_state_changes_pushed_after_an_action_with_timings(self):
        session = FakeTVSession({"actions/sendkey": [
            (BROADCAST_STATE, '{"statetype": "remote_launcher"}')]})
        tv = TV(runner=runner_for(session), wait=0)

        pushes = tv.watch(seconds=1, then=tv.key_message("KEY_HOME"))

        self.assertEqual([state for _, state in pushes], [{"statetype": "remote_launcher"}])
        self.assertGreaterEqual(pushes[0][0], 0)
        self.assertIn((f"/remoteapp/tv/remote_service/{session.client_id}/actions/sendkey", "KEY_HOME"),
                      session.published)

    def test_stops_as_soon_as_the_wanted_state_arrives(self):
        session = FakeTVSession({"actions/launchapp": [
            (BROADCAST_STATE, '{"statetype": "app", "name": "Netflix"}')]})
        tv = TV(runner=runner_for(session), wait=0)

        pushes = tv.watch(seconds=30, then=tv.launch_message({"appId": "1", "name": "Netflix", "url": "netflix"}),
                          until=lambda s: s.get("name") == "Netflix")

        self.assertEqual(pushes[-1][1]["name"], "Netflix")

    def test_a_quiet_tv_yields_no_pushes(self):
        tv = TV(runner=runner_for(FakeTVSession()), wait=0)

        self.assertEqual(tv.watch(seconds=0.2), [])


class WatchCallbackTest(unittest.TestCase):
    def test_every_push_reaches_the_callback(self):
        session = FakeTVSession({"actions/sendkey": [
            (BROADCAST_STATE, '{"statetype": "remote_launcher"}'),
            (BROADCAST_STATE, '{"statetype": "app", "name": "netflix"}')]})
        tv = TV(runner=runner_for(session), wait=0)
        seen = []

        tv.watch(seconds=0.3, then=tv.key_message("KEY_HOME"), on_push=seen.append)

        self.assertEqual([s["statetype"] for s in seen], ["remote_launcher", "app"])
