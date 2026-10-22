// Native apps can't be started from a web page on this firmware, so they go
// through the Mac relay (which opened this page with #relay=...). Web apps
// open directly when the relay is away.
const PRIVATE_RELAY =
  /^http:\/\/(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):\d{2,5}\/[A-Za-z0-9_-]{6,}$/;

export function relayFrom(hash) {
  const value = new URLSearchParams(String(hash).replace(/^#/, '')).get('relay');
  return value && PRIVATE_RELAY.test(value) ? value : null;
}

export function planLaunch(tile, relay) {
  if (relay && tile.kind === 'classic') return { action: 'navigate', url: `${relay}/classic` };
  if (relay) return { action: 'navigate', url: `${relay}/launch/${encodeURIComponent(tile.id)}` };
  if (tile.url) return { action: 'navigate', url: tile.url };
  return { action: 'hint', tile };
}

// With the relay running, the last tile hands the screen back to VIDAA's own
// home (for its Settings and app store) and pauses the auto-return for a while.
const CLASSIC = { id: 'classic', name: { ro: 'Ecran VIDAA', en: 'VIDAA home' }, glyph: 'grid', kind: 'classic' };

export function dockFor(tiles, relay) {
  return relay ? [...tiles, CLASSIC] : tiles;
}
