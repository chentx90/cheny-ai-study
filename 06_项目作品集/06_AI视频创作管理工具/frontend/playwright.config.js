import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5174',
    browserName: 'chromium',
    channel: 'msedge',
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
  },
  reporter: 'line',
});
