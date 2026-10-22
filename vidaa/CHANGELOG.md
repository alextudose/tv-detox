# Changelog

## 0.1.0 (2026-10-22)

First version for Hisense VIDAA TVs.

- Pairing with the TV's PIN over its MQTT remote-control channel (via Sidee), with a clock-skew guard.
- Read-only backup of the TV: app list, inputs, device info, UPnP descriptor, pairing session.
- Change journal written before every change, and a restore that undoes all runs newest first.
- NextDNS: profile backup, query observation, batch blocking of hosts the TV was seen calling,
  never touching updates, the app store, DRM, the launcher, the account or the phone remote.
- Calm home screen on GitHub Pages: dock of apps and inputs, Carpathian photos with credits,
  Romanian or English from the TV's menu language, service worker cache.
- Mac relay (launchd) that opens native apps and inputs for the home, with optional auto-return.
- Speed timings (launch and Home) to compare before and after.
