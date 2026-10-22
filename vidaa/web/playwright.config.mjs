import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  outputDir: 'test-results',
  use: { baseURL: 'http://127.0.0.1:4719', locale: 'ro-RO', timezoneId: 'Europe/Bucharest' },
  webServer: {
    command: 'python3 -m http.server 4719 --bind 127.0.0.1',
    url: 'http://127.0.0.1:4719/index.html',
    reuseExistingServer: false,
  },
});
