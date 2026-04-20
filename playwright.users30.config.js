const { defineConfig } = require('@playwright/test');

const baseURL = process.env.HELMET_USERS30_BASE_URL || 'http://127.0.0.1:8001';
const python = process.env.HELMET_E2E_PYTHON || 'python';
const parsedBaseURL = new URL(baseURL);
const localHost = ['127.0.0.1', 'localhost'].includes(parsedBaseURL.hostname);
const localPort = Number(parsedBaseURL.port || 8001);

const config = defineConfig({
  testDir: './e2e',
  testMatch: /users30-current\.spec\.js/,
  timeout: 900000,
  expect: { timeout: 20000 },
  fullyParallel: false,
  workers: Number(process.env.HELMET_USERS30_UI_WORKERS || 1),
  reporter: [['line']],
  outputDir: 'test-results/users30-playwright-artifacts',
  use: {
    baseURL,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
});

if (localHost) {
  config.webServer = {
    command: `"${python}" scripts/run_api_server.py`,
    url: `${parsedBaseURL.origin}/health`,
    reuseExistingServer: true,
    timeout: 240000,
    env: {
      ...process.env,
      HELMET_API_HOST: '127.0.0.1',
      HELMET_API_PORT: String(localPort),
    },
  };
}

module.exports = config;
