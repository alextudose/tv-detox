"""The iPhone as a camera pointed at the TV, through Safari: no app and no
Apple ID. The phone page long-polls this Mac; a capture request is answered
with a JPEG drawn from the live camera."""
from __future__ import annotations

import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .shot import CameraError

PHONE_PORT = 8443
CONTROL_PORT = 8444
POLL_SECONDS = 20


class FrameBroker:
    """Pairs capture requests from the CLI with frames from the phone."""

    def __init__(self):
        self._cond = threading.Condition()
        self._pending: list[str] = []
        self._frames: dict[str, bytes | None] = {}

    def request(self, timeout: float) -> bytes | None:
        request_id = secrets.token_hex(8)
        with self._cond:
            self._pending.append(request_id)
            self._frames[request_id] = None
            self._cond.notify_all()
            self._cond.wait_for(lambda: self._frames.get(request_id) is not None, timeout)
            frame = self._frames.pop(request_id, None)
            if request_id in self._pending:
                self._pending.remove(request_id)
            return frame

    def next_request(self, timeout: float) -> str | None:
        with self._cond:
            if self._cond.wait_for(lambda: bool(self._pending), timeout):
                return self._pending.pop(0)
            return None

    def deliver(self, request_id: str, frame: bytes) -> bool:
        with self._cond:
            if request_id not in self._frames:
                return False
            self._frames[request_id] = frame
            self._cond.notify_all()
            return True


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TV camera</title>
<style>body{margin:0;background:#000;color:#ddd;font:16px -apple-system,sans-serif}
video{width:100vw;height:80vh;object-fit:contain;background:#111}
button{font-size:20px;padding:14px 28px;margin:12px;border-radius:12px;border:0}
#s{padding:0 12px}</style></head><body>
<video id="v" playsinline muted autoplay></video>
<button id="go">Start camera</button><div id="s">Point the phone at the TV, then tap Start.</div>
<canvas id="c" hidden></canvas>
<script>
const v = document.getElementById('v'), c = document.getElementById('c'), s = document.getElementById('s');
let shots = 0;
async function loop() {
  for (;;) {
    try {
      const r = await fetch('next', {cache: 'no-store'});
      if (r.status !== 200) continue;
      const id = await r.text();
      c.width = v.videoWidth; c.height = v.videoHeight;
      c.getContext('2d').drawImage(v, 0, 0);
      const blob = await new Promise(ok => c.toBlob(ok, 'image/jpeg', 0.9));
      await fetch('frame?id=' + id, {method: 'POST', body: blob, headers: {'Content-Type': 'image/jpeg'}});
      s.textContent = 'Sent photo #' + (++shots) + ' (' + c.width + 'x' + c.height + '). Keep this page open.';
    } catch (e) { s.textContent = 'Reconnecting... ' + e; await new Promise(ok => setTimeout(ok, 2000)); }
  }
}
document.getElementById('go').onclick = async () => {
  try {
    v.srcObject = await navigator.mediaDevices.getUserMedia({audio: false,
      video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1080}}});
    if (navigator.wakeLock) { try { await navigator.wakeLock.request('screen'); } catch (e) {} }
    document.getElementById('go').hidden = true;
    s.textContent = 'Ready. Keep the TV in frame and this page open.';
    loop();
  } catch (e) { s.textContent = 'Camera blocked: ' + e; }
};
</script></body></html>"""


def _phone_handler(broker: FrameBroker, token: str):
    prefix = f"/{token}/"

    class Phone(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes = b"", kind: str = "text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == prefix:
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif path == prefix + "next":
                request_id = broker.next_request(POLL_SECONDS)
                self._send(200, request_id.encode()) if request_id else self._send(204)
            else:
                self._send(404)

        def do_POST(self):
            url = urlsplit(self.path)
            if url.path != prefix + "frame":
                return self._send(404)
            frame = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            request_id = parse_qs(url.query).get("id", [""])[0]
            self._send(200 if broker.deliver(request_id, frame) else 410)

    return Phone


def _control_handler(broker: FrameBroker, capture_timeout: float):
    class Control(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/capture":
                self.send_response(404)
                self.end_headers()
                return
            frame = broker.request(capture_timeout)
            self.send_response(200 if frame else 504)
            self.send_header("Content-Length", str(len(frame or b"")))
            self.end_headers()
            self.wfile.write(frame or b"")

    return Control


def serve(phone_host: str, phone_port: int = PHONE_PORT, control_port: int = CONTROL_PORT,
          token: str | None = None, tls=None, capture_timeout: float = 15.0):
    """Start the phone listener (TLS on the LAN) and the local control
    listener. Returns both servers, already serving in background threads."""
    broker = FrameBroker()
    phone = ThreadingHTTPServer((phone_host, phone_port), _phone_handler(broker, token or secrets.token_urlsafe(8)))
    if tls is not None:
        phone.socket = tls.wrap_socket(phone.socket, server_side=True)
    control = ThreadingHTTPServer(("127.0.0.1", control_port), _control_handler(broker, capture_timeout))
    for server in (phone, control):
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return phone, control


class PhoneCamera:
    """Same interface as shot.Camera, backed by the phone page."""

    def __init__(self, control_url: str = f"http://127.0.0.1:{CONTROL_PORT}", timeout: float = 20.0):
        self.control_url = control_url
        self.timeout = timeout

    def capture(self, out: str | Path) -> Path:
        out = Path(out)
        try:
            req = urllib.request.Request(self.control_url + "/capture", data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout + 5) as r:
                frame = r.read()
        except urllib.error.HTTPError as e:
            raise CameraError("the phone did not send a photo: is the camera page open and awake?") from e
        except OSError as e:
            raise CameraError(f"phone camera server not running ({e}); start `vidaa-detox phonecam`") from e
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(frame)
        return out
