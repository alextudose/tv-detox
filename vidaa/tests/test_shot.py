import subprocess
import tempfile
import unittest
from pathlib import Path

from detox.shot import Camera, CameraError

# Real `ffmpeg -f avfoundation -list_devices true -i ""` stderr from this Mac.
MAC_ONLY = """\
[AVFoundation indev @ 0x75f3020140] AVFoundation video devices:
[AVFoundation indev @ 0x75f3020140] [0] MacBook Pro Camera
[AVFoundation indev @ 0x75f3020140] [1] MacBook Pro Desk View Camera
[AVFoundation indev @ 0x75f3020140] [2] Capture screen 0
[AVFoundation indev @ 0x75f3020140] [3] Capture screen 1
[AVFoundation indev @ 0x75f3020140] AVFoundation audio devices:
[AVFoundation indev @ 0x75f3020140] [0] MacBook Pro Microphone
[AVFoundation indev @ 0x75f3020140] [1] Splashtop Remote Sound
"""
WITH_IPHONE = MAC_ONLY.replace("[2] Capture screen 0", "[2] iPhone Camera").replace(
    "[3] Capture screen 1", "[3] Capture screen 0")


class FakeFfmpeg:
    def __init__(self, listing, capture_rc=0, capture_err=""):
        self.listing, self.capture_rc, self.capture_err = listing, capture_rc, capture_err
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if "-list_devices" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", self.listing)
        if self.capture_rc == 0:
            Path(cmd[-1]).write_bytes(b"\xff\xd8jpeg")
        return subprocess.CompletedProcess(cmd, self.capture_rc, "", self.capture_err)


class PickTest(unittest.TestCase):
    def test_prefers_the_iphone_continuity_camera(self):
        self.assertEqual(Camera(run=FakeFfmpeg(WITH_IPHONE)).pick(), (2, "iPhone Camera"))

    def test_falls_back_to_the_built_in_camera_never_a_screen_or_desk_view(self):
        self.assertEqual(Camera(run=FakeFfmpeg(MAC_ONLY)).pick(), (0, "MacBook Pro Camera"))

    def test_audio_devices_are_not_cameras(self):
        names = [n for _, n in Camera(run=FakeFfmpeg(MAC_ONLY)).devices()]
        self.assertNotIn("MacBook Pro Microphone", names)

    def test_no_camera_at_all_is_an_error(self):
        listing = "[AVFoundation indev @ 0x1] AVFoundation video devices:\n" \
                  "[AVFoundation indev @ 0x1] [0] Capture screen 0\n"
        with self.assertRaises(CameraError):
            Camera(run=FakeFfmpeg(listing)).pick()


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.out = Path(self.dir.name) / "shots" / "01-home.jpg"

    def tearDown(self):
        self.dir.cleanup()

    def test_captures_one_settled_frame_from_the_chosen_camera(self):
        ffmpeg = FakeFfmpeg(WITH_IPHONE)

        path = Camera(run=ffmpeg).capture(self.out)

        self.assertTrue(path.exists())
        cmd = ffmpeg.calls[-1]
        self.assertEqual(cmd[cmd.index("-i") + 1], "2:none")
        self.assertIn("-frames:v", cmd)

    def test_a_refused_camera_explains_the_macos_permission(self):
        ffmpeg = FakeFfmpeg(MAC_ONLY, capture_rc=1, capture_err="Failed to create AV capture input device")

        with self.assertRaises(CameraError) as raised:
            Camera(run=ffmpeg).capture(self.out)

        self.assertIn("Camera", str(raised.exception))
        self.assertIn("Privacy", str(raised.exception))
