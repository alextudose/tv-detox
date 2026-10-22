"""The Mac relay: the calm home asks it to open native apps (a web page on
this TV cannot), and it can reopen the home whenever VIDAA's own launcher
shows up. Everything here is undone by stopping the relay."""
from __future__ import annotations

import html
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .tv import TVError

DEBOUNCE = 5.0          # ignore the launcher showing right after we opened the home
CLASSIC_PAUSE = 600.0   # "VIDAA home" tile: stay out of the way for ten minutes

PAGE = """<!doctype html><meta charset="utf-8"><title>{title}</title>
<body style="margin:0;height:100vh;display:grid;place-items:center;background:#060a08;color:#eef2ea;
font:28px system-ui,sans-serif">{text}<script>{script}</script></body>"""


class Relay:
    def __init__(self, tv, tiles, token, home_id, home_url, self_url, auto_home, clock=time.time):
        self.tv, self.token, self.clock = tv, token, clock
        self.tiles = {t["id"]: t for t in tiles}
        self.home_id, self.home_url, self.self_url = home_id, home_url, self_url
        self.auto_home = auto_home
        self.last_home_launch = float("-inf")
        self.paused_until = float("-inf")

    def handle(self, path: str) -> tuple[int, str]:
        parts = path.strip("/").split("/")
        if len(parts) < 2 or parts[0] != self.token:
            return 404, ""
        if parts[1:] == ["classic"]:
            self.paused_until = self.clock() + CLASSIC_PAUSE
            self.tv.send_key("KEY_HOME")
            return 200, PAGE.format(title="VIDAA", text="VIDAA", script="")
        if len(parts) != 3 or parts[1] != "launch" or parts[2] not in self.tiles:
            return 404, ""
        tile = self.tiles[parts[2]]
        name = tile["name"] if isinstance(tile["name"], str) else next(iter(tile["name"].values()))
        try:
            if tile["kind"] == "source":
                self.tv.change_source(tile["source"])
            else:
                self.tv.launch(tile["app"])
        except TVError as e:
            return 502, PAGE.format(title=html.escape(name), text=html.escape(str(e)),
                                    script="setTimeout(function(){history.back()},4000)")
        # if the TV ignores us, return to the home instead of leaving this page on screen
        return 200, PAGE.format(title=html.escape(name), text=html.escape(name),
                                script="setTimeout(function(){history.back()},10000)")

    def home_address(self) -> str:
        return f"{self.home_url}#relay={self.self_url}"

    def on_state(self, state: dict) -> None:
        now = self.clock()
        if (not self.auto_home or state.get("statetype") != "remote_launcher"
                or now < self.paused_until or now - self.last_home_launch < DEBOUNCE):
            return
        self.last_home_launch = now
        self.tv.open_url(self.home_id, "Acasă", self.home_address())


def serve(relay: Relay, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            status, body = relay.handle(self.path.split("?")[0])
            raw = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
