const { defineConfig } = require('@playwright/test');

const port = Number(process.env.E2E_PORT || 39123);
const python = process.env.HELMET_E2E_PYTHON || 'python';

module.exports = defineConfig({
  testDir: './e2e',
  testIgnore: /users30-current\.spec\.js/,
  timeout: 120000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['line']],
  outputDir: 'test-results/playwright-artifacts',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: `"${python}" scripts/run_e2e_server.py`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 240000,
    env: {
      ...process.env,
      E2E_PORT: String(port),
    },
  },
});
