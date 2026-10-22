import { keyAction, moveFocus } from './focus.js';
import { dockFor, planLaunch, relayFrom } from './launch.js';
import { formatClock, languageOf } from './clock.js';
import { isDue, nextWallpaper } from './wallpaper.js';

const params = new URLSearchParams(location.search);
const INTERVAL = Number(params.get('interval')) || 5 * 60 * 1000;
const relay = relayFrom(location.hash);
const lang = languageOf(window.Hisense_GetMenuLanguageCode?.(), navigator.language);
const TEXT = {
  ro: { hint: (app) => `Pentru ${app}, apasă Home și alege-l din rândul VIDAA.`, credit: (a, l) => `Foto: ${a}, ${l}` },
  en: {
    hint: (app) => `To open ${app}, press Home and pick it from the VIDAA row.`,
    credit: (a, l) => `Photo: ${a}, ${l}`,
  },
}[lang];
const GLYPHS = {
  antenna:
    '<path d="M12 21V11"/><path d="M8 6.5a5.5 5.5 0 0 1 8 0"/><path d="M5 3.5a9.5 9.5 0 0 1 14 0"/><circle cx="12" cy="10" r="1.4"/><path d="M8 21h8"/>',
  grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
  gamepad:
    '<rect x="2.5" y="7" width="19" height="10" rx="5"/><path d="M7.5 10.5v3M6 12h3"/><circle cx="15.5" cy="11" r=".9"/><circle cx="17.5" cy="13" r=".9"/>',
};
const label = (name) => (typeof name === 'string' ? name : name[lang]);
const $ = (id) => document.getElementById(id);
document.documentElement.lang = lang;

function store(key, value) {
  try {
    value === undefined ? (value = localStorage.getItem(key)) : localStorage.setItem(key, value);
  } catch {
    value = null;
  }
  return value;
}

// --- Dock ---
let tiles = [];
let focus = 0;

function renderDock() {
  $('dock').innerHTML = '';
  tiles.forEach((tile, i) => {
    const slot = document.createElement('li');
    slot.className = tile.glyph ? 'slot has-text' : 'slot';
    slot.dataset.id = tile.id;
    const face = tile.icon
      ? `<div class="tile${tile.fit === 'cover' ? ' cover' : ''}" style="--bg:${tile.bg}"><img src="${tile.icon}" alt=""></div>`
      : `<div class="tile source"><svg viewBox="0 0 24 24">${GLYPHS[tile.glyph]}</svg><span>${label(tile.name)}</span></div>`;
    slot.innerHTML = `${face}<div class="name">${label(tile.name)}</div>`;
    $('dock').append(slot);
  });
  setFocus(Math.min(Number(store('focus')) || 0, tiles.length - 1));
}

function setFocus(index) {
  focus = index;
  [...$('dock').children].forEach((slot, i) => slot.classList.toggle('is-focused', i === index));
  store('focus', String(index));
}

let hintTimer;
function showHint(text) {
  $('hint').textContent = text;
  $('hint').classList.add('is-shown');
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => $('hint').classList.remove('is-shown'), 6000);
}

function open(tile) {
  const plan = planLaunch(tile, relay);
  if (plan.action === 'navigate') location.href = plan.url;
  else showHint(TEXT.hint(label(tile.name)));
}

document.addEventListener('keydown', (event) => {
  const action = keyAction(event.keyCode);
  if (!action || !tiles.length) return;
  event.preventDefault();
  if (action === 'open') open(tiles[focus]);
  else setFocus(moveFocus(focus, action, tiles.length));
});

// --- Clock ---
function tick() {
  const { time, date } = formatClock(new Date(), lang);
  $('time').textContent = time;
  $('date').textContent = date;
  setTimeout(tick, 60000 - (Date.now() % 60000) + 50);
}

// --- Wallpapers: two layers, one opacity crossfade ---
let photos = [];
let history = [];
let shownAt = 0;
let front = 'photo-a';

function showPhoto(index) {
  const photo = photos[index];
  const img = new Image();
  img.onload = () => {
    const back = front === 'photo-a' ? 'photo-b' : 'photo-a';
    $(back).style.backgroundImage = `url("${photo.file}")`;
    $(back).classList.add('is-shown');
    $(front).classList.remove('is-shown');
    front = back;
    $('place').textContent = photo.place;
    $('credit').textContent = TEXT.credit(photo.author, photo.license);
    history = [...history.slice(-31), index];
    shownAt = Date.now();
    store('photo', String(index));
    const upcoming = nextWallpaper(photos, history, new Date());
    new Image().src = photos[upcoming].file; // warm the cache for the next fade
  };
  img.src = photo.file;
}

setInterval(
  () => {
    if (photos.length > 1 && isDue(shownAt, Date.now(), INTERVAL))
      showPhoto(nextWallpaper(photos, history, new Date()));
  },
  Math.min(INTERVAL, 15000),
);

// --- Start ---
Promise.all([fetch('apps.json').then((r) => r.json()), fetch('wallpapers/credits.json').then((r) => r.json())]).then(
  ([apps, credits]) => {
    tiles = dockFor(apps.tiles, relay);
    photos = credits;
    renderDock();
    const last = Number(store('photo'));
    showPhoto(
      Number.isInteger(last) && last >= 0 && last < photos.length ? nextWallpaper(photos, [last], new Date()) : 0,
    );
  },
);
tick();

if (location.protocol === 'https:' && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
