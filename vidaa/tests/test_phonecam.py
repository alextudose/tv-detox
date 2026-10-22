import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from detox.phonecam import FrameBroker, PhoneCamera, serve
from detox.shot import CameraError

JPEG = b"\xff\xd8\xff\xe0 fake tv frame"


class FakePhone(threading.Thread):
    """Plays the Safari page: long-poll for a request, answer with a frame."""

    def __init__(self, base):
        super().__init__(daemon=True)
        self.base = base

    def run(self):
        with urllib.request.urlopen(self.base + "next", timeout=10) as r:
            request_id = r.read().decode()
        req = urllib.request.Request(self.base + f"frame?id={request_id}", data=JPEG, method="POST",
                                     headers={"Content-Type": "image/jpeg"})
        urllib.request.urlopen(req, timeout=10).read()


class BrokerTest(unittest.TestCase):
    def test_a_capture_request_is_answered_by_the_frame_the_phone_delivers(self):
        broker = FrameBroker()
        result = {}
        waiter = threading.Thread(target=lambda: result.update(frame=broker.request(timeout=5)))
        waiter.start()

        request_id = broker.next_request(timeout=5)
        broker.deliver(request_id, JPEG)
        waiter.join(5)

        self.assertEqual(result["frame"], JPEG)

    def test_no_phone_means_the_request_times_out(self):
        self.assertIsNone(FrameBroker().request(timeout=0.2))

    def test_a_frame_for_an_unknown_request_is_ignored(self):
        self.assertFalse(FrameBroker().deliver("not-a-request", JPEG))


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.servers = serve(phone_host="127.0.0.1", phone_port=0, control_port=0, token="t0k3n", tls=None,
                             capture_timeout=1, control_token="c0ntr0l")
        phone, control = self.servers
        self.phone_base = f"http://127.0.0.1:{phone.server_port}/t0k3n/"
        self.control_url = f"http://127.0.0.1:{control.server_port}"
        self.camera = PhoneCamera(self.control_url, timeout=5, token="c0ntr0l")
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        self.dir.cleanup()

    def test_a_shot_is_the_frame_sent_by_the_phone(self):
        FakePhone(self.phone_base).start()

        path = self.camera.capture(Path(self.dir.name) / "shots" / "01-home.jpg")

        self.assertEqual(path.read_bytes(), JPEG)

    def test_the_phone_page_is_served_only_behind_the_token(self):
        with urllib.request.urlopen(self.phone_base, timeout=5) as r:
            self.assertIn(b"getUserMedia", r.read())
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.phone_base.replace("t0k3n", "guess"), timeout=5)
        self.assertEqual(raised.exception.code, 404)

    def test_no_phone_connected_is_a_camera_error(self):
        camera = PhoneCamera(self.camera.control_url, timeout=0.5, token="c0ntr0l")

        with self.assertRaises(CameraError) as raised:
            camera.capture(Path(self.dir.name) / "x.jpg")

        self.assertIn("phone", str(raised.exception).lower())

    def _capture_status(self, headers):
        req = urllib.request.Request(self.control_url + "/capture", data=b"", method="POST", headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_capture_needs_the_control_token(self):
        self.assertEqual(self._capture_status({}), 403)
        self.assertEqual(self._capture_status({"X-Capture-Token": "guess"}), 403)

    def test_capture_rejects_a_foreign_host_header_against_dns_rebinding(self):
        port = self.servers[1].server_port
        self.assertEqual(self._capture_status({"X-Capture-Token": "c0ntr0l", "Host": f"evil.example:{port}"}), 403)

    def test_server_not_running_is_a_camera_error(self):
        with self.assertRaises(CameraError):
            PhoneCamera("http://127.0.0.1:9", timeout=0.5).capture(Path(self.dir.name) / "x.jpg")


class WiringTest(unittest.TestCase):
    def test_shots_use_the_phone_when_its_server_is_up_otherwise_the_mac_camera(self):
        from detox.cli import pick_camera
        from detox.shot import Camera

        phone, control = serve(phone_host="127.0.0.1", phone_port=0, control_port=0, token="x", tls=None,
                               control_token="c")
        try:
            self.assertIsInstance(pick_camera(control.server_port), PhoneCamera)
        finally:
            for s in (phone, control):
                s.shutdown()
                s.server_close()
        self.assertIsInstance(pick_camera(control.server_port), Camera)

    def test_the_phone_url_is_printed_as_a_scannable_square_qr(self):
        from detox.cli import qr_lines

        lines = qr_lines("https://192.168.1.129:8443/t0k3n/")

        self.assertGreater(len(lines), 10)
        self.assertEqual(len({len(line) for line in lines}), 1, "every row has the same width")
