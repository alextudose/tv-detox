import { test } from 'node:test';
import assert from 'node:assert/strict';
import { moveFocus, keyAction } from '../js/focus.js';
import { relayFrom, planLaunch, dockFor } from '../js/launch.js';
import { formatClock, languageOf } from '../js/clock.js';
import { isDue, nextWallpaper } from '../js/wallpaper.js';

test('left and right wrap around the dock', () => {
  assert.equal(moveFocus(0, 'left', 7), 6);
  assert.equal(moveFocus(6, 'right', 7), 0);
  assert.equal(moveFocus(3, 'right', 7), 4);
});

test('remote keys map to actions and other keys do nothing', () => {
  assert.equal(keyAction(37), 'left');
  assert.equal(keyAction(39), 'right');
  assert.equal(keyAction(13), 'open');
  assert.equal(keyAction(403), null); // red: unused for now
});

test('the relay is only trusted on a private LAN address with a token', () => {
  assert.equal(relayFrom('#relay=http://192.168.1.129:8788/Ab3_xY9z'), 'http://192.168.1.129:8788/Ab3_xY9z');
  assert.equal(relayFrom('#relay=http://evil.example.com:8788/Ab3_xY9z'), null);
  assert.equal(relayFrom('#relay=http://192.168.1.129:8788/'), null);
  assert.equal(relayFrom(''), null);
  assert.equal(relayFrom('#relay=javascript:alert(1)'), null);
});

const netflix = { id: 'netflix', kind: 'app', app: 'Netflix' };
const stremio = {
  id: 'stremio',
  kind: 'app',
  app: 'Stremio Lite',
  url: 'https://relvhgchz5.strem.io/hello-world/index.html',
};

test('with the relay every tile launches through it', () => {
  assert.deepEqual(planLaunch(netflix, 'http://192.168.1.129:8788/tok'), {
    action: 'navigate',
    url: 'http://192.168.1.129:8788/tok/launch/netflix',
  });
});

test('without the relay web apps open directly and native apps get a hint', () => {
  assert.deepEqual(planLaunch(stremio, null), { action: 'navigate', url: stremio.url });
  assert.deepEqual(planLaunch(netflix, null), { action: 'hint', tile: netflix });
});

test('the clock speaks the TV language: Romanian 24h time and date', () => {
  const at = new Date('2026-10-22T18:47:00Z');
  assert.deepEqual(formatClock(at, 'ro', 'Europe/Bucharest'), { time: '21:47', date: 'joi, 22 octombrie' });
  assert.deepEqual(formatClock(at, 'en', 'Europe/Bucharest'), { time: '21:47', date: 'Thursday 22 October' });
});

test('menu language codes become UI languages', () => {
  assert.equal(languageOf('rum', 'en-US'), 'ro');
  assert.equal(languageOf('ron', 'en-US'), 'ro');
  assert.equal(languageOf(undefined, 'ro-RO'), 'ro');
  assert.equal(languageOf('eng', 'en-US'), 'en');
});

test('a new photo is due once the interval has passed', () => {
  assert.equal(isDue(0, 299_000, 300_000), false);
  assert.equal(isDue(0, 300_000, 300_000), true);
});

test('the next wallpaper is always a different, valid photo', () => {
  const photos = Array.from({ length: 16 }, (_, i) => ({ file: `wallpapers/${i + 1}.jpg` }));
  let history = [0];
  for (let i = 0; i < 40; i++) {
    const next = nextWallpaper(photos, history, new Date(2026, 9, 22, i % 24));
    assert.ok(Number.isInteger(next) && next >= 0 && next < photos.length);
    assert.notEqual(next, history.at(-1));
    history = [...history, next];
  }
});

test('the VIDAA home tile goes through the relay and only exists with it', () => {
  const classic = { id: 'classic', kind: 'classic' };
  assert.deepEqual(planLaunch(classic, 'http://192.168.1.129:8788/tok'), {
    action: 'navigate',
    url: 'http://192.168.1.129:8788/tok/classic',
  });
  assert.deepEqual(
    dockFor([netflix], 'http://192.168.1.129:8788/tok').map((t) => t.id),
    ['netflix', 'classic'],
  );
  assert.deepEqual(
    dockFor([netflix], null).map((t) => t.id),
    ['netflix'],
  );
});
