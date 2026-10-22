import { test, expect } from '@playwright/test';

const SIZES = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
];

for (const size of SIZES) {
  test(`dock and plate fit the ${size.width}x${size.height} screen`, async ({ page }) => {
    await page.setViewportSize(size);
    await page.goto('/index.html');
    const slots = page.locator('.slot');
    await expect(slots).toHaveCount(7);
    await expect(page.locator('#time')).toHaveText(/^\d{2}:\d{2}$/);
    await expect(page.locator('#place')).not.toBeEmpty();
    const last = await slots.last().boundingBox();
    expect(last.x + last.width).toBeLessThan(size.width);
    await page.waitForTimeout(1400); // let the first photo fade in
    await page.screenshot({ path: `test-results/home-${size.width}.png` });
  });
}

test('the D-pad moves focus along the dock and wraps', async ({ page }) => {
  await page.goto('/index.html');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  const focused = page.locator('.slot.is-focused');
  await expect(focused).toHaveAttribute('data-id', 'netflix');
  await page.keyboard.press('ArrowRight');
  await expect(focused).toHaveAttribute('data-id', 'youtube');
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  await expect(focused).toHaveAttribute('data-id', 'console');
});

test('without the Mac relay a native app shows how to open it, in Romanian', async ({ page }) => {
  await page.goto('/index.html');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.locator('.slot.is-focused')).toHaveAttribute('data-id', 'netflix');
  await page.keyboard.press('Enter');
  await expect(page.locator('#hint')).toHaveClass(/is-shown/);
  await expect(page.locator('#hint')).toHaveText('Pentru Netflix, apasă Home și alege-l din rândul VIDAA.');
});

test('without the relay a web app opens directly', async ({ page }) => {
  await page.route('https://relvhgchz5.strem.io/**', (route) => route.fulfill({ body: '<title>Stremio</title>' }));
  await page.goto('/index.html');
  await page.evaluate(() => localStorage.setItem('focus', '3'));
  await page.reload();
  await expect(page.locator('.slot.is-focused')).toHaveAttribute('data-id', 'stremio');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL('https://relvhgchz5.strem.io/hello-world/index.html');
});

test('with the relay a native app is launched through it', async ({ page }) => {
  await page.route('http://192.168.1.129:8788/**', (route) => route.fulfill({ body: 'launching' }));
  await page.goto('/index.html#relay=http://192.168.1.129:8788/tok123');
  await page.evaluate(() => localStorage.clear());
  await page.goto('/index.html?fresh#relay=http://192.168.1.129:8788/tok123');
  await expect(page.locator('.slot.is-focused')).toHaveAttribute('data-id', 'netflix');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL('http://192.168.1.129:8788/tok123/launch/netflix');
});

test('photos crossfade to the next one with its own caption', async ({ page }) => {
  await page.goto('/index.html?interval=1500');
  await page.evaluate(() => localStorage.clear());
  await page.goto('/index.html?interval=1500&fresh');
  const place = page.locator('#place');
  await expect(place).not.toBeEmpty();
  const first = await place.textContent();
  const firstCredit = await page.locator('#credit').textContent();
  await expect.poll(async () => page.locator('#credit').textContent(), { timeout: 20000 }).not.toBe(firstCredit);
  await expect(page.locator('.photo.is-shown')).toHaveCount(1);
  expect(await place.textContent()).toBeTruthy();
  expect(first).toBeTruthy();
});

test('with the relay the extra VIDAA tile still fits on a 1280 screen', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/index.html#relay=http://192.168.1.129:8788/tok123');
  const slots = page.locator('.slot');
  await expect(slots).toHaveCount(8);
  const last = await slots.last().boundingBox();
  expect(last.x + last.width).toBeLessThanOrEqual(1280 - 60);
  await expect(page.locator('.photo.is-shown')).toHaveCount(1);
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('.slot.is-focused')).toHaveCount(1);
  await expect(page.locator('.slot.is-focused')).toHaveAttribute('data-id', 'classic');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: 'test-results/home-relay-1280.png' });
});
