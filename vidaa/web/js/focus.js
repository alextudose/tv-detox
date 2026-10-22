// D-pad focus along the single dock row. Back and Menu never reach web pages on VIDAA.
const KEYS = { 37: 'left', 39: 'right', 13: 'open' };

export function keyAction(keyCode) {
  return KEYS[keyCode] ?? null;
}

export function moveFocus(index, action, count) {
  if (action === 'left') return (index - 1 + count) % count;
  if (action === 'right') return (index + 1) % count;
  return index;
}
