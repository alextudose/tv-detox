"""vidaa-detox: pair with the TV, back it up, photograph it, and drive it."""
from __future__ import annotations

import argparse
import email.utils
import json
import os
import re
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import phonecam
from . import relay as relay_mod
from .manifest import Manifest
from .nextdns import NextDNS, NextDNSError, plan_batch
from .shot import Camera, CameraError
from .tv import TV, TVError, sidee

TV_HOST = os.environ.get("VIDAA_TV", "192.168.1.132")
RUNS = Path(__file__).resolve().parent.parent / "runs"
BLOCKLIST = Path(__file__).resolve().parent.parent / "blocklist"
WEB = Path(__file__).resolve().parent.parent / "web"
AGENT = "io.github.alextudose.tvdetox.relay"
HOME_ID = "calmhome"
RELAY_PORT = 8788


def _sidee_add_tile(app_id: str, name: str, url: str, image: str) -> None:
    client = sidee()
    apps = client.add_tile(client.Session().load(), app_id, name, url, image)
    if not any(client.tile_matches_request(a, app_id, url) for a in apps):
        raise TVError(f"the TV did not confirm the {name} tile")


def _launchctl(args: list[str]) -> None:
    subprocess.run(["launchctl", *args], check=False, capture_output=True)
MAX_SKEW = 60  # the TV refuses logins beyond ~120 s; stop well before that


def _fetch(url: str) -> tuple[str, str]:
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode("utf-8", "replace"), r.headers.get("Date", "")


PHONECAM_DIR = Path(__file__).resolve().parent.parent / ".phonecam"


def pick_camera(control_port: int = phonecam.CONTROL_PORT, token_file: Path = PHONECAM_DIR / "control-token"):
    """The phone camera page when its server is running, else the Mac's camera."""
    with socket.socket() as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", control_port)) == 0:
            token = token_file.read_text().strip() if token_file.exists() else ""
            return phonecam.PhoneCamera(f"http://127.0.0.1:{control_port}", token=token)
    return Camera()


def qr_lines(text: str) -> list[str]:
    """A QR code drawn with half-block characters, two modules per line."""
    sidee()
    from core._qrcodegen import QrCode
    qr = QrCode.encode_text(text, QrCode.Ecc.LOW)
    n, quiet = qr.get_size(), 2
    dark = lambda x, y: 0 <= x < n and 0 <= y < n and qr.get_module(x, y)
    rows = []
    for y in range(-quiet, n + quiet, 2):
        rows.append("".join(" " if dark(x, y) and dark(x, y + 1) else
                            "\u2584" if dark(x, y) else "\u2580" if dark(x, y + 1) else "\u2588"
                            for x in range(-quiet, n + quiet)))
    return rows


@dataclass
class Deps:
    tv: Callable[[str], TV] = TV
    camera: Camera = field(default_factory=pick_camera)
    fetch: Callable[[str], tuple[str, str]] = _fetch
    now: Callable[[], float] = time.time
    session_path: Path = Path.home() / ".sidee" / "session.json"
    runs: Path = RUNS
    host: str = TV_HOST
    pair: Callable | None = None  # sidee.client.pair, injectable for tests
    dns: Callable[[], NextDNS] | None = None
    add_tile: Callable[[str, str, str, str], None] = _sidee_add_tile
    launchctl: Callable[[list[str]], None] = _launchctl
    agents: Path = Path.home() / "Library" / "LaunchAgents"
    ask: Callable[[str], str] = input


def _hosts(name: str) -> list[str]:
    return [l.strip() for l in (BLOCKLIST / name).read_text().splitlines() if l.strip() and not l.startswith("#")]


def _dns(deps: Deps) -> NextDNS:
    if deps.dns:
        return deps.dns()
    profile_file = deps.runs / "nextdns-profile"
    profile = os.environ.get("NEXTDNS_PROFILE") or (profile_file.read_text().strip() if profile_file.exists() else "")
    if not profile:
        raise ValueError(f"set NEXTDNS_PROFILE or write the profile id to {profile_file}")
    return NextDNS(profile)


def _renderer_url(host: str) -> str:
    return f"http://{host}:38400/MediaServer/rendererdevicedesc.xml"


def _new_run(deps: Deps) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(deps.now()))
    deps.runs.mkdir(parents=True, exist_ok=True)
    name, n = stamp, 1
    while (deps.runs / name).exists():  # never merge two runs
        n += 1
        name = f"{stamp}-{n}"
    run = deps.runs / name
    run.mkdir()
    (deps.runs / "CURRENT").write_text(name)
    return run


def _current_run(deps: Deps) -> Path:
    marker = deps.runs / "CURRENT"
    if marker.exists() and (deps.runs / marker.read_text().strip()).is_dir():
        return deps.runs / marker.read_text().strip()
    return _new_run(deps)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_skew(args, deps: Deps) -> int:
    _, date = deps.fetch(_renderer_url(deps.host))
    skew = round(deps.now() - email.utils.parsedate_to_datetime(date).timestamp())
    if abs(skew) > MAX_SKEW:
        print(f"Mac clock is {skew} s off the TV clock; fix the time before pairing", file=sys.stderr)
        return 2
    print(f"clock skew {skew} s (ok)")
    return 0


def _pin_reader(pin_file: str | None, timeout: float = 120.0):
    """The PIN comes from the keyboard, or from a file written by someone
    reading it off the TV while this waits."""
    if not pin_file:
        return lambda: input("PIN shown on the TV: ").strip()

    def read() -> str:
        path, deadline = Path(pin_file), time.time() + timeout
        print(f"waiting for the PIN in {path}", flush=True)
        while time.time() < deadline:
            if path.exists() and (pin := path.read_text().strip()):
                path.unlink()
                return pin
            time.sleep(0.5)
        return ""
    return read


def cmd_pair(args, deps: Deps) -> int:
    if cmd_skew(args, deps):
        return 2
    pair = deps.pair or sidee().pair
    session = pair(deps.host, _pin_reader(args.pin_file))
    print(f"paired ({session.auth_profile} login); token saved in {deps.session_path}")
    return 0


def cmd_backup(args, deps: Deps) -> int:
    tv = deps.tv(deps.host)
    backup = _new_run(deps) / "backup"
    backup.mkdir()
    body, _ = deps.fetch(_renderer_url(deps.host))
    (backup / "renderer.xml").write_text(body)
    for name, read in (("state", tv.state), ("applist", tv.apps),
                       ("sourcelist", tv.sources), ("info", tv.info)):
        try:
            _write_json(backup / f"{name}.json", read())
        except TVError as e:
            print(f"warning: {name}: {e}", file=sys.stderr)
    if deps.session_path.exists():
        copy = backup / "session.json"
        shutil.copyfile(deps.session_path, copy)
        os.chmod(copy, 0o600)
    print(f"backup saved to {backup}")
    return 0


def cmd_shot(args, deps: Deps) -> int:
    run = _current_run(deps)
    shots = run / "shots"
    number = len(list(shots.glob("*.jpg"))) + 1 if shots.exists() else 1
    slug = re.sub(r"[^a-z0-9]+", "-", args.label.lower()).strip("-")
    path = deps.camera.capture(shots / f"{number:02d}-{slug}.jpg")
    try:
        state = json.dumps(deps.tv(deps.host).state(), ensure_ascii=False)
    except TVError:
        state = "no state (TV silent)"
    stamp = time.strftime("%H:%M:%S", time.localtime(deps.now()))
    with open(run / "journal.md", "a") as journal:
        journal.write(f"- {stamp} **{args.label}** `shots/{path.name}` state: `{state}`\n")
    print(path)
    return 0


def _first_time(pushes, wanted) -> float | None:
    return next((t for t, state in pushes if wanted(state)), None)


def cmd_speed(args, deps: Deps) -> int:
    """Seconds from a launch request until the TV reports the app, and from
    Home until it reports the launcher: same procedure before and after."""
    tv = deps.tv(deps.host)
    apps = {a["name"].lower(): a for a in tv.apps()}
    on_home = lambda s: s.get("statetype") == "remote_launcher"
    result = {}
    for name in [n.strip() for n in args.apps.split(",")]:
        app = apps.get(name.lower())
        if not app:
            print(f"warning: {name} is not on the TV", file=sys.stderr)
            continue
        record = {k: app[k] for k in ("appId", "name", "url")}
        launches, homes = [], []
        for _ in range(args.rounds):
            pushes = tv.watch(args.timeout, then=tv.launch_message(record),
                              until=lambda s: s.get("statetype") == "app")
            launches.append(_first_time(pushes, lambda s: s.get("statetype") == "app"))
            homes.append(_first_time(tv.watch(args.timeout, then=tv.key_message("KEY_HOME"), until=on_home), on_home))
            time.sleep(args.settle)
        timed = lambda xs: [x for x in xs if x is not None]
        result[app["name"]] = {
            "launch_s": launches, "home_s": homes,
            "median_launch_s": statistics.median(timed(launches)) if timed(launches) else None,
            "median_home_s": statistics.median(timed(homes)) if timed(homes) else None}
        print(f"{app['name']}: launch {result[app['name']]['median_launch_s']} s, "
              f"home {result[app['name']]['median_home_s']} s (median of {args.rounds})", flush=True)
    _write_json(_current_run(deps) / f"speed-{args.label}.json", result)
    return 0


def cmd_dns(args, deps: Deps) -> int:
    dns, run = _dns(deps), _current_run(deps)
    deny, allow = _hosts("hisense-deny.txt"), _hosts("hisense-allow.txt")
    manifest = Manifest(run / "manifest.json")
    if args.dns_cmd == "backup":
        (run / "backup").mkdir(exist_ok=True)
        _write_json(run / "backup" / "nextdns-profile.json", dns.profile())
        print(f"NextDNS profile saved to {run / 'backup' / 'nextdns-profile.json'}")
        return 0
    if args.dns_cmd == "observe":
        seen = dns.domain_counts(since=args.since)
        _write_json(run / "dns-observed.json", seen)
        for domain, c in sorted(seen.items(), key=lambda kv: -kv[1]["queries"]):
            verdict = ("never block" if domain in allow else "candidate" if domain in deny else "")
            print(f"{c['queries']:6d} q {c['blocked']:5d} blocked  {domain}  {verdict}")
        return 0
    if args.dns_cmd == "block":
        already = [e["id"] for e in dns.denylist()]
        batch = plan_batch(dns.domain_counts(since=args.since), deny, allow, already, args.size)
        print("next batch:" if batch else "nothing left to block", *batch, sep="\n  ")
        if not args.yes:
            return 0
        for domain in batch:
            entry = manifest.record(kind="dns-deny", target=domain, before="resolves", after="blocked",
                                    undo=f"vidaa-detox dns unblock {domain}")
            try:
                dns.deny(domain)
            except NextDNSError as e:
                manifest.mark(entry, "failed")
                print(f"error: {domain}: {e}", file=sys.stderr)
                return 1
            manifest.mark(entry, "applied")
        return 0
    targets = ([e for e in manifest.to_restore() if e["kind"] == "dns-deny" and e["status"] != "failed"]
               if args.ours else [{"target": d, "id": None} for d in args.domains])
    for e in targets:
        dns.undeny(e["target"])
        if e["id"]:
            manifest.mark(e["id"], "reverted")
        print(f"unblocked {e['target']}")
    return 0


def cmd_home(args, deps: Deps) -> int:
    url = args.url if args.url.endswith("/") else args.url + "/"
    if not url.startswith("https://"):
        raise ValueError("the home must be served over https (GitHub Pages)")
    manifest = Manifest(_current_run(deps) / "manifest.json")
    entry = manifest.record(kind="tile", target=args.tile_id, before="absent", after=url,
                            undo="TV: Apps > Apps on Home > remove the Acasă tile")
    try:
        deps.add_tile(args.tile_id, args.name, url, url + "icon.png")
    except TVError:
        manifest.mark(entry, "failed")
        raise
    manifest.mark(entry, "applied")
    (deps.runs / "home-url").write_text(url)
    (deps.runs / "home-tile-id").write_text(args.tile_id)
    print(f"home tile {args.tile_id!r} -> {url}")
    return 0


def _agent_plist(deps: Deps, auto_home: bool) -> str:
    project = Path(__file__).resolve().parent.parent
    argv = [shutil.which("uv") or "uv", "run", "--project", str(project), "python", "-m", "detox",
            "relay", "run"] + (["--auto-home"] if auto_home else [])
    log = deps.runs / "relay.log"
    items = "".join(f"<string>{a}</string>" for a in argv)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{AGENT}</string>
<key>ProgramArguments</key><array>{items}</array>
<key>WorkingDirectory</key><string>{project}</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""


def _relay_token(deps: Deps) -> str:
    path = deps.runs / "relay-token"
    if not path.exists():
        path.write_text(phonecam.secrets.token_urlsafe(18))
        os.chmod(path, 0o600)
    return path.read_text().strip()


def cmd_relay(args, deps: Deps) -> int:
    home_file = deps.runs / "home-url"
    plist = deps.agents / f"{AGENT}.plist"
    target = f"gui/{os.getuid()}"
    if args.relay_cmd == "uninstall":
        deps.launchctl(["bootout", target, str(plist)])
        plist.unlink(missing_ok=True)
        manifest = Manifest(_current_run(deps) / "manifest.json")
        for e in manifest.to_restore():
            if e["kind"] == "relay":
                manifest.mark(e["id"], "reverted")
        print("relay stopped and removed")
        return 0
    if not home_file.exists():
        raise ValueError("install the home tile first: vidaa-detox home install --url <pages url>")
    token = _relay_token(deps)
    if args.relay_cmd == "install":
        manifest = Manifest(_current_run(deps) / "manifest.json")
        entry = manifest.record(kind="relay", target=AGENT, before="absent", after=str(plist),
                                undo="vidaa-detox relay uninstall")
        deps.agents.mkdir(parents=True, exist_ok=True)
        plist.write_text(_agent_plist(deps, args.auto_home))
        deps.launchctl(["bootout", target, str(plist)])  # harmless when not loaded
        deps.launchctl(["bootstrap", target, str(plist)])
        manifest.mark(entry, "applied")
        print(f"relay installed ({'auto-home on' if args.auto_home else 'auto-home off'}); log: {deps.runs / 'relay.log'}")
        return 0
    ip = _lan_ip(deps.host)  # relay run
    tiles = json.loads((WEB / "apps.json").read_text())["tiles"]
    tile_file = deps.runs / "home-tile-id"
    home_id = tile_file.read_text().strip() if tile_file.exists() else HOME_ID
    relay = relay_mod.Relay(deps.tv(deps.host), tiles, token, home_id, home_file.read_text().strip(),
                            f"http://{ip}:{RELAY_PORT}/{token}", args.auto_home)
    relay_mod.serve(relay, ip, RELAY_PORT)
    print(f"relay on http://{ip}:{RELAY_PORT}/<token> (auto-home {'on' if args.auto_home else 'off'})", flush=True)
    tv = deps.tv(deps.host)
    while True:  # keep watching; the TV drops the connection when it sleeps
        try:
            tv.watch(300, on_push=relay.on_state)
        except Exception as e:  # noqa: BLE001 - log and keep the relay alive
            print(f"watch: {e}", flush=True)
            time.sleep(15)


RESTORE_GROUPS = {"relay": {"relay"}, "home": {"tile"}, "dns": {"dns-deny", "dns-tv"}, "settings": {"menu"}}


def _journal(deps: Deps) -> list[tuple[Manifest, dict]]:
    """Every change from every run, newest first."""
    runs = sorted((d for d in deps.runs.iterdir() if (d / "manifest.json").exists()), reverse=True) \
        if deps.runs.exists() else []
    return [(m, e) for m in (Manifest(d / "manifest.json") for d in runs) for e in m.to_restore()]


def cmd_restore(args, deps: Deps) -> int:
    kinds = set().union(*(RESTORE_GROUPS[g] for g in args.only.split(","))) if args.only \
        else set().union(*RESTORE_GROUPS.values())
    steps = [(m, e) for m, e in _journal(deps) if e["kind"] in kinds]
    if args.dry_run or not steps:
        print(f"{len(steps)} change(s) to undo, newest first:")
        for _, e in steps:
            print(f"- {e['kind']} {e['target']} (was {e['before']!r}): {e['undo']}")
        return 0
    open_steps, dns = 0, None
    for manifest, e in steps:
        kind, target = e["kind"], e["target"]
        if kind == "relay":
            plist = deps.agents / f"{AGENT}.plist"
            deps.launchctl(["bootout", f"gui/{os.getuid()}", str(plist)])
            plist.unlink(missing_ok=True)
            done = True
        elif kind == "dns-deny":
            dns = dns or _dns(deps)
            dns.undeny(target)
            done = True
        else:
            print(f"\n{kind}: {target}\n  put back: {e['undo']}\n  it was: {e['before']}")
            done = deps.ask("  Done? [y/N] ").strip().lower() == "y"
            if done and kind == "tile":
                done = target not in {a.get("appId") for a in deps.tv(deps.host).apps()}
                if not done:
                    print("  the TV still lists this tile")
        if done:
            manifest.mark(e["id"], "reverted")
            print(f"undone: {kind} {target}")
        else:
            open_steps += 1
    if open_steps:
        print(f"{open_steps} step(s) still open; run restore again to finish them", file=sys.stderr)
        return 1
    print("everything this detox changed is back the way it was")
    return 0


def _printer(read):
    def cmd(args, deps: Deps) -> int:
        print(json.dumps(read(deps.tv(deps.host)), indent=2, ensure_ascii=False))
        return 0
    return cmd


def cmd_launch(args, deps: Deps) -> int:
    print(json.dumps(deps.tv(deps.host).launch(args.name)))
    return 0


def cmd_key(args, deps: Deps) -> int:
    deps.tv(deps.host).send_key(args.key)
    return 0


def cmd_source(args, deps: Deps) -> int:
    print(json.dumps(deps.tv(deps.host).change_source(args.name)))
    return 0


def cmd_open(args, deps: Deps) -> int:
    deps.tv(deps.host).open_url(args.app_id, args.name, args.url)
    return 0


def _lan_ip(toward: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((toward, 9))
        return s.getsockname()[0]


def _tls_context(folder: Path, ip: str) -> ssl.SSLContext:
    """Self-signed certificate for the phone page; Safari asks once to trust it."""
    cert, key = folder / "cert.pem", folder / "key.pem"
    if not cert.exists():
        folder.mkdir(parents=True, exist_ok=True)
        openssl = shutil.which("openssl", path="/opt/homebrew/opt/openssl@3/bin") or "openssl"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "60",
                        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=vidaa-detox camera",
                        "-addext", f"subjectAltName=IP:{ip}"], check=True, capture_output=True)
        os.chmod(key, 0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


def cmd_phonecam(args, deps: Deps) -> int:
    ip = _lan_ip(deps.host)
    token = phonecam.secrets.token_urlsafe(6)
    _, control = phonecam.serve(ip, token=token, tls=_tls_context(PHONECAM_DIR, ip))
    token_file = PHONECAM_DIR / "control-token"
    token_file.write_text(control.control_token)
    os.chmod(token_file, 0o600)
    url = f"https://{ip}:{phonecam.PHONE_PORT}/{token}/"
    print("Scan with the iPhone camera, or open in Safari:\n" + "\n".join(qr_lines(url)) + f"\n{url}", flush=True)
    print("Safari: Show Details > visit this website, then allow the camera and tap Start.", flush=True)
    threading.Event().wait()  # serve until stopped
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vidaa-detox")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("skew", help="compare the Mac and TV clocks").set_defaults(fn=cmd_skew)
    s = sub.add_parser("pair", help="pair with the TV (it shows a PIN)")
    s.add_argument("--pin-file", help="read the PIN from this file instead of the keyboard")
    s.set_defaults(fn=cmd_pair)
    sub.add_parser("backup", help="snapshot the TV into a new run").set_defaults(fn=cmd_backup)
    sub.add_parser("phonecam", help="use the iPhone (Safari) as the TV camera").set_defaults(fn=cmd_phonecam)
    for name, read in (("state", TV.state), ("apps", TV.apps), ("sources", TV.sources), ("info", TV.info)):
        sub.add_parser(name).set_defaults(fn=_printer(read))
    s = sub.add_parser("shot", help="photograph the TV and journal its state")
    s.add_argument("label")
    s.set_defaults(fn=cmd_shot)
    s = sub.add_parser("speed", help="time app launches and Home (before/after)")
    s.add_argument("label")
    s.add_argument("--apps", default="Netflix,YouTube,Prime Video,Stremio Lite")
    s.add_argument("--rounds", type=int, default=3)
    s.add_argument("--timeout", type=float, default=40.0)
    s.add_argument("--settle", type=float, default=3.0, help="pause between rounds")
    s.set_defaults(fn=cmd_speed)
    s = sub.add_parser("dns", help="NextDNS: backup, observe, block in batches, unblock")
    dns = s.add_subparsers(dest="dns_cmd", required=True)
    dns.add_parser("backup")
    for name in ("observe", "block"):
        c = dns.add_parser(name)
        c.add_argument("--since", default="-24h")
        if name == "block":
            c.add_argument("--size", type=int, default=10)
            c.add_argument("--yes", action="store_true", help="apply; without it only the plan is shown")
    c = dns.add_parser("unblock")
    c.add_argument("domains", nargs="*")
    c.add_argument("--ours", action="store_true", help="every host this detox blocked, newest first")
    s.set_defaults(fn=cmd_dns)
    s = sub.add_parser("home", help="register the calm home as a launcher tile")
    home = s.add_subparsers(dest="home_cmd", required=True)
    c = home.add_parser("install")
    c.add_argument("--url", required=True, help="the GitHub Pages address of vidaa/web")
    c.add_argument("--tile-id", default=HOME_ID)
    c.add_argument("--name", default="Acasă")
    s.set_defaults(fn=cmd_home)
    s = sub.add_parser("relay", help="Mac relay for native app launches (and auto-home)")
    rel = s.add_subparsers(dest="relay_cmd", required=True)
    for name in ("run", "install"):
        c = rel.add_parser(name)
        c.add_argument("--auto-home", action="store_true", help="reopen the calm home when VIDAA's launcher shows")
    rel.add_parser("uninstall")
    s.set_defaults(fn=cmd_relay)
    s = sub.add_parser("restore", help="undo every change this detox made, newest first")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--only", help="comma list of: " + ",".join(RESTORE_GROUPS))
    s.set_defaults(fn=cmd_restore)
    s = sub.add_parser("launch", help="open an installed app by name")
    s.add_argument("name")
    s.set_defaults(fn=cmd_launch)
    s = sub.add_parser("key", help="press a remote key, e.g. KEY_HOME")
    s.add_argument("key")
    s.set_defaults(fn=cmd_key)
    s = sub.add_parser("source", help="switch input by name or label")
    s.add_argument("name")
    s.set_defaults(fn=cmd_source)
    s = sub.add_parser("open", help="open a web page as an app (no tile)")
    s.add_argument("app_id")
    s.add_argument("name")
    s.add_argument("url")
    s.set_defaults(fn=cmd_open)
    return p


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args, deps or Deps())
    except (TVError, CameraError, NextDNSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
