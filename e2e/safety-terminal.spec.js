const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const OUTPUT_DIR = path.join(process.cwd(), 'test-results', 'helmet-frontend-audit');
const ADMIN_USERNAME = process.env.HELMET_E2E_ADMIN_USERNAME || 'jianghuajian99@gmail.com';
const ADMIN_PASSWORD = process.env.HELMET_E2E_ADMIN_PASSWORD || 'AdminPass!2026';

function ensureOutputDir() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

function attachDiagnostics(page) {
  const pageErrors = [];
  const consoleErrors = [];
  const failedResponses = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    const text = message.text();
    const expectedRemoteReject = text.includes('400 (Bad Request)');
    if (message.type() === 'error' && !expectedRemoteReject) consoleErrors.push(text);
  });
  page.on('response', (response) => {
    const status = response.status();
    if (status >= 400) {
      const url = response.url();
      const expectedRemoteReject = url.includes('/api/v1/helmet/cameras') && status === 400;
      const expectedGuestReject = (url.includes('/api/v1/helmet/accounts') || url.includes('/api/v1/helmet/ops/')) && status === 401;
      if (!expectedRemoteReject && !expectedGuestReject) {
        failedResponses.push(`${status} ${response.request().method()} ${url}`);
      }
    }
  });
  return { pageErrors, consoleErrors, failedResponses };
}

function assertCleanDiagnostics(diag) {
  expect(diag.pageErrors, diag.pageErrors.join('\n')).toEqual([]);
  expect(diag.consoleErrors, diag.consoleErrors.join('\n')).toEqual([]);
  expect(diag.failedResponses, diag.failedResponses.join('\n')).toEqual([]);
}

async function screenshot(page, name) {
  ensureOutputDir();
  await page.screenshot({ path: path.join(OUTPUT_DIR, `${name}.png`), fullPage: true });
}

async function waitForPageReady(page, name) {
  await expect(page.locator(`[data-page-ready="${name}"]`)).toBeVisible({ timeout: 20000 });
}

async function expectNoPageOverflow(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(6);
}

async function expectCanvasPainted(page, selector) {
  const painted = await page.locator(selector).evaluate((canvas) => {
    const ctx = canvas.getContext('2d');
    if (!ctx || !canvas.width || !canvas.height) return false;
    const sample = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let index = 3; index < sample.length; index += 4) {
      if (sample[index] > 0) return true;
    }
    return false;
  });
  expect(painted).toBeTruthy();
}

async function loginAdmin(page) {
  await page.goto('/app/#/login', { waitUntil: 'domcontentloaded' });
  await page.locator('#username').fill(ADMIN_USERNAME);
  await page.locator('#password').fill(ADMIN_PASSWORD);
  await page.locator('#login-btn').click();
  await expect(page).toHaveURL(/#\/dashboard/);
  await expect(page.locator('.topbar-user')).toContainText(/Safety|访客|Guest|Operations|@|Admin/i);
}

test('landing page screenshots and CTA enter dashboard without login', async ({ page }) => {
  const diag = attachDiagnostics(page);

  await page.setViewportSize({ width: 1440, height: 920 });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#s-hero')).toBeVisible();
  await expect(page.locator('#s-product')).toBeVisible();
  await expect(page.locator('#s-cta')).toBeVisible();
  await expect(page.locator('[data-app-entry="dashboard"]').first()).toHaveAttribute('href', '/app/#/dashboard');
  await screenshot(page, 'landing-desktop');

  await page.locator('#s-product').scrollIntoViewIfNeeded();
  await screenshot(page, 'landing-product-section');
  await page.locator('#s-cta').scrollIntoViewIfNeeded();
  await screenshot(page, 'landing-cta-section');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await screenshot(page, 'landing-mobile');

  await page.locator('[data-app-entry="dashboard"]').first().click();
  await expect(page).toHaveURL(/\/app\/#\/dashboard$/);
  await waitForPageReady(page, 'dashboard');
  await expect(page.locator('.topbar-user')).toContainText(/访客|Guest|璁垮/);
  await expectNoPageOverflow(page);

  assertCleanDiagnostics(diag);
});

test('guest can click read-only pages and cannot enter operations studio', async ({ page }) => {
  const diag = attachDiagnostics(page);
  await page.setViewportSize({ width: 1366, height: 860 });

  const routes = [
    ['/dashboard', 'guest-dashboard', 'dashboard'],
    ['/review', 'guest-review', 'review'],
    ['/cameras', 'guest-live-cameras', 'cameras'],
    ['/reports', 'guest-reports', 'reports'],
    ['/hard-cases', 'guest-hard-cases', 'hard-cases'],
    ['/config', 'guest-config', 'config'],
  ];

  for (const [route, shot, ready] of routes) {
    await page.goto(`/app/#${route}`, { waitUntil: 'domcontentloaded' });
    await waitForPageReady(page, ready);
    await expectNoPageOverflow(page);
    await screenshot(page, shot);
  }

  await page.goto('/app/#/dashboard', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'dashboard');
  await page.locator('input[name="visitor_name"]').fill('Guest Auditor');
  await page.locator('input[name="visitor_company"]').fill('Helmet QA');
  await page.locator('input[name="visit_reason"]').fill('Visual audit');
  await page.locator('textarea[name="note"]').fill('Guest mode record for screenshot verification.');
  await page.locator('input[name="snapshot"]').setInputFiles({
    name: 'guest-visitor.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from([0xff, 0xd8, 0xff, 0xd9]),
  });
  const visitorResponse = page.waitForResponse((response) => response.url().includes('/api/v1/helmet/visitor-evidence') && response.request().method() === 'POST');
  await page.locator('#submit-visitor-evidence').click();
  expect((await visitorResponse).status()).toBe(200);
  await expect(page.locator('.visitor-record').first()).toContainText(/Guest Auditor|访客|璁垮/i);
  await expectCanvasPainted(page, '#hour-chart canvas');
  await page.goto('/app/#/config', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'config');
  await expectCanvasPainted(page, '#config-pipeline-canvas');
  await expect(page.locator('.config-command-grid .results-panel')).toBeVisible();

  await page.goto('/app/#/operations', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'dashboard');
  await expect(page).toHaveURL(/#\/dashboard/);

  await page.setViewportSize({ width: 390, height: 844 });
  for (const [route, shot, ready] of [
    ['/dashboard', 'mobile-dashboard', 'dashboard'],
    ['/review', 'mobile-review', 'review'],
    ['/cameras', 'mobile-live-cameras', 'cameras'],
    ['/config', 'mobile-config', 'config'],
  ]) {
    await page.goto(`/app/#${route}`, { waitUntil: 'domcontentloaded' });
    await waitForPageReady(page, ready);
    await expectNoPageOverflow(page);
    await screenshot(page, shot);
  }

  await page.setViewportSize({ width: 1366, height: 860 });
  await page.goto('/app/#/dashboard', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'dashboard');
  await page.locator('#tb-lang-en').click();
  await expect.poll(async () => page.locator('body').innerText(), { timeout: 20000 }).not.toMatch(/[\u4e00-\u9fff]/);
  await screenshot(page, 'guest-dashboard-english');

  await page.locator('#theme-toggle-btn').click();
  await waitForPageReady(page, 'dashboard');
  await screenshot(page, 'guest-dashboard-light');

  await page.goto('/app/#/config', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'config');
  await page.locator('#save-config-camera-btn').click();
  await expect(page).toHaveURL(/#\/login/);

  await page.goto('/app/#/review', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'review');
  if (await page.locator('#assign-case-btn').count()) {
    await page.locator('#assign-case-btn').click();
    await expect(page).toHaveURL(/#\/login/);
  }

  assertCleanDiagnostics(diag);
});

test('admin performs deep interface checks across config, review, cameras, and operations studio', async ({ page }) => {
  const diag = attachDiagnostics(page);
  await page.setViewportSize({ width: 1440, height: 920 });
  await loginAdmin(page);

  await page.goto('/app/#/cameras', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'cameras');
  await expect(page.locator('.camera-selector-bar .camera-selector').first()).toBeVisible();
  await expect(page.locator('.live-camera-card').first()).toBeVisible();
  await screenshot(page, 'admin-live-cameras');

  await page.goto('/app/#/config', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'config');
  await expect(page.locator('#config-pipeline-canvas')).toBeVisible();
  await expect(page.locator('.config-command-grid .results-panel')).toBeVisible();
  await expectCanvasPainted(page, '#config-pipeline-canvas');
  await expect(page.locator('[data-config-camera-id]').first()).toBeVisible();
  await page.locator('[data-config-camera-id]').first().click();
  await page.locator('#cfg-source').fill('1');
  await page.locator('#cfg-camera-name').fill('E2E Local Camera');
  const saveResponsePromise = page.waitForResponse((response) => response.url().includes('/api/v1/helmet/cameras') && response.request().method() === 'POST');
  await page.locator('#save-config-camera-btn').click();
  expect((await saveResponsePromise).status()).toBe(200);
  await waitForPageReady(page, 'config');
  await screenshot(page, 'admin-config-saved');

  await page.goto('/app/#/config', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'config');
  const rejectResponsePromise = page.waitForResponse((response) => response.url().includes('/api/v1/helmet/cameras') && response.request().method() === 'POST');
  await page.locator('#try-remote-source-btn').click();
  expect((await rejectResponsePromise).status()).toBe(400);

  await page.goto('/app/#/review', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'review');
  await expect(page.locator('.review-history-panel')).toBeVisible();
  if (await page.locator('#assign-case-btn').count()) {
    await page.locator('#assignee').fill('e2e-lead');
    await page.locator('#assignee-email').fill('e2e@example.com');
    const assignResponsePromise = page.waitForResponse((response) => response.url().includes('/assign') && response.request().method() === 'POST');
    await page.locator('#assign-case-btn').click();
    expect((await assignResponsePromise).status()).toBe(200);
  }

  await page.goto('/app/#/operations', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'operations');
  await expect(page.locator('#ops-coverage')).toBeVisible();
  await expect(page.locator('#ops-services')).toBeVisible();
  await expect(page.locator('#ops-quality-lab')).toBeVisible();
  await expect(page.locator('#ops-access-admin')).toBeVisible();
  await screenshot(page, 'admin-operations-studio');

  await page.goto('/app/#/operations?section=quality-lab', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'operations');
  await expect(page.locator('#ops-quality-lab')).toBeVisible();

  await page.goto('/app/#/operations?section=notifications', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'operations');
  await expect(page.locator('#ops-notifications')).toBeVisible();

  await page.goto('/app/#/operations?section=access-admin', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'operations');
  await expect(page.locator('#ops-access-admin')).toBeVisible();

  await page.goto('/app/#/reports', { waitUntil: 'domcontentloaded' });
  await waitForPageReady(page, 'reports');
  await expect(page.locator('[data-report-status]').first()).toBeVisible();
  await expect(page.locator('[data-report-camera]').first()).toBeVisible();

  assertCleanDiagnostics(diag);
});


