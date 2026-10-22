export function isDue(lastChangeAt, now, intervalMs) {
  return now - lastChangeAt >= intervalMs;
}

// Which photo comes next. `history` is the indexes shown so far, newest last;
// `now` lets the choice depend on the time of day.
export function nextWallpaper(photos, history, now) {
  // TODO(you): replace this placeholder (simply the next photo in order) with your
  // rotation policy, e.g. shuffle-without-repeat or matching the photo to the time of day.
  const last = history.at(-1) ?? -1;
  return (last + 1) % photos.length;
}
