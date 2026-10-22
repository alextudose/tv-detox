"""The TV over its own MQTT remote-control channel (the one the VIDAA phone
app uses). Connection, pairing and token refresh come from Sidee; this module
adds the read and control operations the detox needs."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

SIDEE = Path(__file__).resolve().parent.parent / "vendor" / "sidee"
BROADCAST_STATE = "/remoteapp/mobile/broadcast/ui_service/state"
KEY_NAME = re.compile(r"KEY_[A-Z0-9_]+")


class TVError(Exception):
    pass


def sidee():
    """Sidee's client module, imported from the pinned submodule."""
    if str(SIDEE) not in sys.path:
        sys.path.insert(0, str(SIDEE))
    from core import client
    return client


def _match(items: list[dict], query: str, *fields: str) -> dict | None:
    q = query.strip().lower()
    for exact in (True, False):
        for item in items:
            for f in fields:
                value = str(item.get(f, "")).lower()
                if (value == q) if exact else value.startswith(q):
                    return item
    return None


class TV:
    def __init__(self, host: str | None = None, runner=None, wait: float = 8.0):
        self.host = host
        self.runner = runner or sidee().run_with_session
        self.wait = wait

    def _ask(self, service: str, action: str, reply_suffixes: list[str], payload: str = "",
             broadcast: list[str] = ()):
        def op(sess, topics):
            mobile = topics["mobile"]
            sess.subscribe([mobile + s for s in reply_suffixes] + list(broadcast))
            time.sleep(0.3 if self.wait else 0)
            since = len(sess.messages)
            sess.publish(topics[service] + "actions/" + action, payload)
            deadline = time.time() + self.wait
            while True:
                for topic, body in sess.messages[since:]:
                    if topic in broadcast or any(topic == mobile + s for s in reply_suffixes):
                        return body
                if time.time() >= deadline:
                    return None
                time.sleep(0.2)

        body, _ = self.runner(op, self.host)
        if body is None:
            raise TVError(f"the TV did not answer {service}/{action}")
        return json.loads(body) if body.strip()[:1] in ("{", "[") else body

    def _tell(self, topic_of, payload: str) -> None:
        def op(sess, topics):
            sess.publish(topic_of(sess, topics), payload)
            time.sleep(0.5 if self.wait else 0)  # let the broker flush before disconnect
        self.runner(op, self.host)

    def state(self) -> dict:
        return self._ask("ui", "gettvstate", ["ui_service/data/state"], broadcast=[BROADCAST_STATE])

    def apps(self) -> list[dict]:
        return self._ask("ui", "applist", ["ui_service/data/applist"], payload="0")

    def sources(self) -> list[dict]:
        return self._ask("ui", "sourcelist", ["ui_service/data/sourcelist"])

    def info(self) -> dict:
        parts = {"tvinfo": ("platform", "gettvinfo", "platform_service/data/gettvinfo"),
                 "deviceinfo": ("platform", "getdeviceinfo", "platform_service/data/getdeviceinfo"),
                 "capability": ("ui", "capability", "ui_service/data/capability")}
        info = {}
        for name, (service, action, reply) in parts.items():
            try:
                info[name] = self._ask(service, action, [reply])
            except TVError:
                info[name] = None
        return info

    @staticmethod
    def key_message(key: str):
        if not KEY_NAME.fullmatch(key or ""):
            raise ValueError(f"not a remote key name: {key!r}")
        return (lambda sess, topics: f"/remoteapp/tv/remote_service/{sess.client_id}/actions/sendkey"), key

    @staticmethod
    def launch_message(record: dict):
        return (lambda sess, topics: topics["ui"] + "actions/launchapp"), json.dumps(record)

    def send_key(self, key: str) -> None:
        self._tell(*self.key_message(key))

    def watch(self, seconds: float, then=None, until=None, on_push=None) -> list[tuple[float, dict]]:
        """State pushes from the TV, timed from the moment `then` (a message
        from key_message/launch_message) is sent. This firmware only reports
        state when it changes, so watching is how state is observed."""
        def op(sess, topics):
            sess.subscribe([BROADCAST_STATE])
            time.sleep(0.5 if self.wait else 0)
            seen, start = len(sess.messages), time.time()
            if then:
                topic_of, payload = then
                sess.publish(topic_of(sess, topics), payload)
            pushes = []
            while True:
                for topic, body in sess.messages[seen:]:
                    if topic == BROADCAST_STATE:
                        state = json.loads(body) if body.strip()[:1] == "{" else {"raw": body}
                        pushes.append((round(time.time() - start, 2), state))
                        if on_push:
                            on_push(state)
                        if until and until(state):
                            return pushes
                seen = len(sess.messages)
                if time.time() - start >= seconds:
                    return pushes
                time.sleep(0.1)

        pushes, _ = self.runner(op, self.host)
        return pushes

    def launch(self, name: str) -> dict:
        apps = self.apps()
        app = _match(apps, name, "name")
        if not app:
            have = ", ".join(a.get("name", "?") for a in apps)
            raise TVError(f"no app called {name!r} on the TV; it has: {have}")
        record = {"appId": app["appId"], "name": app["name"], "url": app["url"]}
        self._tell(*self.launch_message(record))
        return record

    def open_url(self, app_id: str, name: str, url: str) -> None:
        """Open a web page as an app, without registering a launcher tile."""
        sidee()
        from core import protocol
        self._tell(lambda sess, topics: topics["ui"] + "actions/launchapp",
                   protocol.launch_payload(app_id, name, url))

    def change_source(self, name: str) -> dict:
        sources = self.sources()
        source = _match(sources, name, "sourcename", "displayname")
        if not source:
            have = ", ".join(f"{s.get('sourcename')} ({s.get('displayname')})" for s in sources)
            raise TVError(f"no input called {name!r}; the TV has: {have}")
        record = {"sourceid": source["sourceid"], "sourcename": source["sourcename"]}
        self._tell(lambda sess, topics: topics["ui"] + "actions/changesource", json.dumps(record))
        return record
