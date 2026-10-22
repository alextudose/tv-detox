# TV Detox for VIDAA

The Hisense VIDAA version of [TV Detox](../README.md). VIDAA is Linux, not Android, so there is no `adb`
and the Android home screen can't run on it. This folder does the same job with what VIDAA offers:

- **Its own remote-control channel** (MQTT on port 36669, the one the VIDAA phone app uses). You pair once
  with the PIN the TV shows. No exploits, nothing installed on the TV's system.
- **DNS blocking** through a NextDNS profile, so ad, tracking and recommendation hosts can't be reached,
  in small batches you approve, and only hosts the TV was actually seen calling.
- **A calm home screen**: a web page on GitHub Pages, registered as a launcher tile, with a dock of your apps
  and rotating Carpathian landscapes.
- **A restore** that undoes all of it, newest change first.

Nothing is ever uninstalled.

## What VIDAA can't do

These are limits of the TV, checked on a 55A51HEVS (VIDAA U09.09, firmware V0002.09.09C.P0930):

- **No remote screenshots** (the TV reports `screen_capture_supported: 0`).
- **No remote control of the Settings menus.** Privacy switches (ACR, personalised ads, recommendations)
  have to be changed with the remote. DNS blocking backs them up if one switches itself back on.
- **The Home button always opens VIDAA's launcher.** It can't be replaced. With the relay running,
  the calm home comes back within about a second.
- **A web page can't start native apps** (Netflix, YouTube, Prime Video) or switch inputs. The relay on your
  Mac does it for the page. When the Mac is asleep, web apps (Stremio, Apple TV) still open; native
  tiles tell you to pick the app from the VIDAA row.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and a Mac on the same network as the TV.

```sh
cd vidaa
git submodule update --init                  # Sidee: pairing and tiles (MIT)
uv run python -m detox pair                  # the TV shows a PIN; type it in
sh backup.sh                                 # snapshot before changing anything
uv run python -m detox speed before          # launch timings to compare later
```

DNS blocking is optional (not enabled on the TV this was built on). To use it, create a NextDNS profile,
point the TV's DNS at it, and save the API key in the Keychain as `vidaa-detox-nextdns`:

```sh
echo <profile-id> > runs/nextdns-profile
uv run python -m detox dns backup
uv run python -m detox dns observe           # what the TV calls home to
uv run python -m detox dns block             # shows the next batch of at most 10
uv run python -m detox dns block --yes       # applies it
```

Home screen (after pushing this branch and enabling GitHub Pages with the `vidaa home` workflow):

```sh
uv run python -m detox home install --url https://<you>.github.io/tv-detox/
uv run python -m detox relay install --auto-home     # optional: native launches and auto-return
```

Edit `web/apps.json` to change the dock (`kind: app` opens an installed app by name,
`kind: source` switches input, e.g. your console's `HDMI1`). `scripts/wallpapers.json` lists the photos;
`uv run python scripts/fetch_wallpapers.py download scripts/wallpapers.json` fetches them again.

## Undo

```sh
sh restore.sh --dry-run          # what would be undone, newest first
sh restore.sh                    # undo: relay and DNS automatically, menu steps guided
sh restore.sh --only dns         # one part: relay, home, dns, settings
```

Every change is written to `runs/<time>/manifest.json` before it's made, so a restore also covers a run
that stopped halfway. Menu switches and removing the home tile need the remote; the restore tells you
exactly where and checks the app list afterwards.

## Tests

```sh
uv run coverage run -m unittest discover -s tests -t . && uv run coverage report
cd web && npm ci && npm test && npx playwright test
```

## Credits

- [Sidee](https://github.com/Empi9245/Sidee) (MIT) for pairing, sessions and tiles.
- Block and allow lists seeded from [Okazakee/tv-dns-blocklist](https://github.com/Okazakee/tv-dns-blocklist).
- Photos from Wikimedia Commons; author and license are shown on screen and listed in
  `web/wallpapers/credits.json`.
- Fraunces and Atkinson Hyperlegible fonts (SIL Open Font License, see `web/fonts/`).
