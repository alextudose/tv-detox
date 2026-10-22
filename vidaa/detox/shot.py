"""Photos of the TV screen. VIDAA has no remote screenshot, so a camera
pointed at the TV (ideally an iPhone via Continuity Camera) is the evidence."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

DEVICE = re.compile(r"\] \[(\d+)\] (.+)$")
NOT_A_CAMERA = ("Capture screen", "Desk View")
SETTLE_FRAMES = 45  # ~1.5 s at 30 fps so exposure and focus settle on the bright TV


class CameraError(Exception):
    pass


class Camera:
    def __init__(self, run=subprocess.run, prefer: tuple[str, ...] = ("iPhone",)):
        self.run = run
        self.prefer = prefer

    def devices(self) -> list[tuple[int, str]]:
        listing = self.run(["ffmpeg", "-hide_banner", "-f", "avfoundation",
                            "-list_devices", "true", "-i", ""],
                           capture_output=True, text=True).stderr
        found, in_video = [], False
        for line in listing.splitlines():
            if "video devices:" in line:
                in_video = True
            elif "audio devices:" in line:
                in_video = False
            elif in_video and (m := DEVICE.search(line)):
                found.append((int(m.group(1)), m.group(2).strip()))
        return found

    def pick(self) -> tuple[int, str]:
        cameras = [d for d in self.devices() if not any(x in d[1] for x in NOT_A_CAMERA)]
        if not cameras:
            raise CameraError("no camera found: put the iPhone near the Mac, locked and in landscape")
        for wanted in self.prefer:
            for device in cameras:
                if wanted.lower() in device[1].lower():
                    return device
        return cameras[0]

    def capture(self, out: str | Path) -> Path:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        index, name = self.pick()
        result = self.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
                           "-framerate", "30", "-i", f"{index}:none",
                           "-vf", f"select=gte(n\\,{SETTLE_FRAMES})", "-frames:v", "1",
                           "-q:v", "2", "-y", str(out)],
                          capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not out.exists():
            raise CameraError(
                f"{name} did not give a frame ({result.stderr.strip()[:200]}). "
                "If macOS blocked it, allow your terminal under System Settings > "
                "Privacy & Security > Camera, then retry.")
        return out
