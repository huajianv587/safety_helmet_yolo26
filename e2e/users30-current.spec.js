const fs = require('fs');
const path = require('path');
const { test, expect, request: requestFactory } = require('@playwright/test');

const COUNT = Number(process.env.HELMET_USERS30_COUNT || 30);
const RUN_ID = process.env.HELMET_USERS30_RUN_ID || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
const BASE_URL = (process.env.HELMET_USERS30_BASE_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
const ROOT = process.cwd();
const OUTPUT_DIR = path.join(ROOT, 'test-results', 'helmet-frontend-audit', '30-users', RUN_ID);
const ROUTES = [
  { path: '/dashboard', ready: 'dashboard' },
  { path: '/review', ready: 'review' },
  { path: '/cameras', ready: 'cameras' },
  { path: '/reports', ready: 'reports' },
  { path: '/hard-cases', ready: 'hard-cases' },
  { path: '/config', ready: 'config' },
  { path: '/operations', ready: 'operations' },
];
const UI_CONCURRENCY = Number(process.env.HELMET_USERS30_UI_CONCURRENCY || 1);
const API_CONCURRENCY = Number(process.env.HELMET_USERS30_API_CONCURRENCY || 5);

function readDotEnvValue(key) {
  const envPath = path.join(ROOT, '.env');
  if (!fs.existsSync(envPath)) return '';
  const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const index = trimmed.indexOf('=');
    if (index < 0) continue;
    const name = trimmed.slice(0, index).trim();
    if (name !== key) continue;
    return trimmed.slice(index + 1).trim().replace(/^['"]|['"]$/g, '');
  }
  return '';
}

function resolveRepoPath(value, fallback) {
  const chosen = value || fallback;
  if (!chosen) return '';
  return path.isAbsolute(chosen) ? chosen : path.join(ROOT, chosen);
}

function ensureOutputDir() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

function backupFile(filePath, label, audit) {
  if (!filePath || !fs.existsSync(filePath)) {
    audit.backups.push({ label, filePath, copied: false, reason: 'missing' });
    return '';
  }
  ensureOutputDir();
  const target = path.join(OUTPUT_DIR, `${label}.backup.${Date.now()}.json`);
  fs.copyFileSync(filePath, target);
  audit.backups.push({ label, filePath, copied: true, backup: target });
  return target;
}

function restoreFile(filePath, backupPath, label, audit) {
  if (!filePath || !backupPath || !fs.existsSync(backupPath)) return;
  fs.copyFileSync(backupPath, filePath);
  audit.restores.push({ label, filePath, backup: backupPath, restored: true });
}

function makeUsers() {
  return Array.from({ length: COUNT }, (_, index) => {
    const suffix = String(index + 1).padStart(2, '0');
    return {
      index,
      username: `helmet_test30_${RUN_ID}_${suffix}@example.test`,
      display_name: `Helmet Test ${suffix}`,
      email: `helmet_test30_${RUN_ID}_${suffix}@example.test`,
      password: `HelmetStart!${RUN_ID}_${suffix}`,
      newPassword: `HelmetChanged!${RUN_ID}_${suffix}`,
      token: '',
      newToken: '',
    };
  });
}

async function runBatches(items, concurrency, worker) {
  const results = [];
  for (let start = 0; start < items.length; start += concurrency) {
    const slice = items.slice(start, start + concurrency);
    const output = await Promise.all(slice.map(worker));
    results.push(...output);
  }
  return results;
}

async function parseResponse(response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    return { text };
  }
}

async function apiCall(api, method, url, options = {}, audit, label, allowStatuses = []) {
  const started = Date.now();
  const response = await api[method](url, options);
  const body = await parseResponse(response);
  const elapsed = Date.now() - started;
  audit.timings.push({ label, method: method.toUpperCase(), url, status: response.status(), ms: elapsed });
  if (!response.ok() && !allowStatuses.includes(response.status())) {
    throw new Error(`${label} failed: ${response.status()} ${JSON.stringify(body).slice(0, 500)}`);
  }
  return { response, body, elapsed };
}

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function attachDiagnostics(page, audit, label) {
  const diag = { pageErrors: [], consoleErrors: [], failedResponses: [] };
  page.on('pageerror', (error) => diag.pageErrors.push(error.message));
  page.on('console', (message) => {
    const expectedRemoteReject = message.text().includes('400 (Bad Request)');
    if (message.type() === 'error' && !expectedRemoteReject) diag.consoleErrors.push(message.text());
  });
  page.on('response', (response) => {
    const status = response.status();
    if (status < 400) return;
    const url = response.url();
    const allowedMediaMiss = url.includes('/api/v1/helmet/media/') && status === 404;
    const allowedFavicon = url.endsWith('/favicon.ico') && status === 404;
    const allowedRouteGuard = url.includes('/api/v1/helmet/ops/') && status === 401;
    if (!allowedMediaMiss && !allowedFavicon && !allowedRouteGuard) {
      diag.failedResponses.push(`${status} ${response.request().method()} ${url}`);
    }
  });
  audit.uiDiagnostics.push({ label, ...diag });
  return diag;
}

function assertCleanDiagnostics(diag, label) {
  expect(diag.pageErrors, `${label} pageerror\n${diag.pageErrors.join('\n')}`).toEqual([]);
  expect(diag.consoleErrors, `${label} console error\n${diag.consoleErrors.join('\n')}`).toEqual([]);
  expect(diag.failedResponses, `${label} failed responses\n${diag.failedResponses.join('\n')}`).toEqual([]);
}

async function screenshot(page, name) {
  ensureOutputDir();
  await page.screenshot({ path: path.join(OUTPUT_DIR, `${name}.png`), fullPage: true });
}

async function waitAppReady(page) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForSelector('#app-root.page-ready', { timeout: 30000 });
  await page.waitForFunction(() => document.body.innerText.trim().length > 20, null, { timeout: 30000 });
}

async function waitRouteReady(page, ready) {
  await page.waitForSelector(`[data-page-ready="${ready}"]`, { timeout: 30000 });
  await waitAppReady(page);
}

async function expectNoPageOverflow(page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(8);
}

async function expectVisibleImagesNotBroken(page) {
  const broken = await page.evaluate(() => Array.from(document.images)
    .filter((image) => getComputedStyle(image).display !== 'none')
    .filter((image) => image.complete && image.naturalWidth === 0)
    .map((image) => image.currentSrc || image.src));
  expect(broken, broken.join('\n')).toEqual([]);
}

async function loginViaUi(page, user) {
  await page.goto('/app/#/login', { waitUntil: 'domcontentloaded' });
  await page.locator('#username').fill(user.username);
  await page.locator('#password').fill(user.newPassword);
  await page.locator('#login-btn').click();
  await expect(page).toHaveURL(/#\/dashboard/, { timeout: 30000 });
  await waitAppReady(page);
  await expect(page.locator('.topbar-user')).toContainText(user.display_name, { timeout: 20000 });
}

async function uiRouteSmoke(browser, user, audit) {
  const context = await browser.newContext({
    viewport: user.index % 2 === 0 ? { width: 1440, height: 980 } : { width: 390, height: 844 },
  });
  const page = await context.newPage();
  const label = `user-${String(user.index + 1).padStart(2, '0')}`;
  const diag = attachDiagnostics(page, audit, label);
  try {
    await loginViaUi(page, user);
    for (const route of ROUTES) {
      const started = Date.now();
      await page.goto(`/app/#${route.path}`, { waitUntil: 'domcontentloaded' });
      await waitRouteReady(page, route.ready);
      await expectNoPageOverflow(page);
      await expectVisibleImagesNotBroken(page);
      audit.clicks.push({ user: user.username, route: route.path, ms: Date.now() - started });
      if (user.index < 2 && ['/dashboard', '/review', '/cameras', '/config', '/operations'].includes(route.path)) {
        await screenshot(page, `${label}-${route.path.slice(1)}-${user.index % 2 === 0 ? 'desktop' : 'mobile'}`);
      }
    }
    assertCleanDiagnostics(diag, label);
  } finally {
    await context.close();
  }
}

async function writeAudit(audit, users, cleanup) {
  ensureOutputDir();
  const payload = {
    ...audit,
    runId: RUN_ID,
    baseURL: BASE_URL,
    count: COUNT,
    cleanup,
    users: users.map((user) => ({ username: user.username, display_name: user.display_name })),
  };
  fs.writeFileSync(path.join(OUTPUT_DIR, 'audit.json'), JSON.stringify(payload, null, 2), 'utf8');
  const avg = (items) => items.length ? Math.round(items.reduce((sum, item) => sum + item.ms, 0) / items.length) : 0;
  const md = [
    `# 30 Users Lifecycle Audit`,
    ``,
    `- Run ID: ${RUN_ID}`,
    `- Base URL: ${BASE_URL}`,
    `- Users: ${COUNT}`,
    `- API calls: ${audit.timings.length}, avg ${avg(audit.timings)} ms`,
    `- UI clicks: ${audit.clicks.length}, avg ${avg(audit.clicks)} ms`,
    `- Created: ${audit.created.length}`,
    `- Password changed: ${audit.passwordChanged.length}`,
    `- Cleanup deleted: ${cleanup.deleted.length}`,
    `- Cleanup already gone: ${cleanup.alreadyGone.length}`,
    `- Cleanup failed: ${cleanup.failed.length}`,
    `- Screenshots: ${OUTPUT_DIR}`,
  ].join('\n');
  fs.writeFileSync(path.join(OUTPUT_DIR, 'audit.md'), md, 'utf8');
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loginWithRetry(api, username, password, audit, label, attempts = 4) {
  let last = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const result = await apiCall(api, 'post', '/auth/login', {
      data: { username, password },
    }, audit, `${label} attempt ${attempt}`, [401, 423]);
    if (result.response.status() === 200) return result;
    last = result;
    await delay(Math.min(1200, attempt * 250));
  }
  throw new Error(`${label} failed: ${last?.response?.status()} ${JSON.stringify(last?.body || {}).slice(0, 500)}`);
}

test('30 users register, login, change password, click pages, and clean up on current environment', async ({ page, browser }, testInfo) => {
  test.setTimeout(900000);
  ensureOutputDir();
  const api = await requestFactory.newContext({ baseURL: BASE_URL });
  const users = makeUsers();
  const audit = {
    backups: [],
    restores: [],
    timings: [],
    clicks: [],
    created: [],
    passwordChanged: [],
    uiDiagnostics: [],
    writeChecks: [],
  };
  const cleanup = { deleted: [], alreadyGone: [], failed: [], verifiedGone: false };

  const authUsersPath = resolveRepoPath(
    process.env.HELMET_AUTH_USERS_FILE || readDotEnvValue('HELMET_AUTH_USERS_FILE'),
    path.join('artifacts', 'runtime', 'ops', 'auth_users.json'),
  );
  const configPath = resolveRepoPath(process.env.HELMET_CONFIG_PATH || readDotEnvValue('HELMET_CONFIG_PATH'), '');
  const authBackup = backupFile(authUsersPath, 'auth_users', audit);
  const configBackup = backupFile(configPath, 'runtime_config', audit);

  let cleanupToken = '';
  try {
    const diag = attachDiagnostics(page, audit, 'primary-ui');
    const first = users[0];
    await page.goto('/app/#/register', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-page-ready="register"]')).toBeVisible();
    await screenshot(page, 'register-page');
    await page.locator('#register-username').fill(first.username);
    await page.locator('#register-display').fill(first.display_name);
    await page.locator('#register-email').fill(first.email);
    await page.locator('#register-password').fill(first.password);
    await page.locator('#register-confirm').fill(first.password);
    await page.locator('#register-btn').click();
    await expect(page).toHaveURL(/#\/dashboard/, { timeout: 30000 });
    await waitAppReady(page);
    await screenshot(page, 'registered-dashboard');
    audit.created.push(first.username);

    await page.goto('/app/#/operations?section=access-admin', { waitUntil: 'domcontentloaded' });
    await waitRouteReady(page, 'operations');
    page.once('dialog', (dialog) => dialog.accept(first.newPassword));
    const changePasswordResponse = page.waitForResponse((response) => response.url().includes('/auth/change-password') && response.request().method() === 'POST');
    await page.locator('#ops-change-password').click();
    expect((await changePasswordResponse).status()).toBe(200);
    await expect(page).toHaveURL(/#\/login/, { timeout: 30000 });
    await screenshot(page, 'change-password-success');
    audit.passwordChanged.push(first.username);

    await page.locator('#username').fill(first.username);
    await page.locator('#password').fill(first.newPassword);
    await screenshot(page, 'login-with-new-password');
    const firstNewLogin = await loginWithRetry(api, first.username, first.newPassword, audit, 'first new password login');
    first.newToken = firstNewLogin.body.token;
    cleanupToken = first.newToken;
    await page.evaluate(({ token, user }) => {
      localStorage.setItem('helmet-token', token);
      localStorage.setItem('helmet-user', JSON.stringify(user));
      sessionStorage.removeItem('helmet-token');
      sessionStorage.removeItem('helmet-user');
    }, { token: first.newToken, user: firstNewLogin.body.user });
    await page.goto('/app/#/dashboard', { waitUntil: 'domcontentloaded' });
    await waitAppReady(page);
    const firstOldLogin = await apiCall(api, 'post', '/auth/login', { data: { username: first.username, password: first.password } }, audit, 'first old password rejected', [401, 423]);
    expect([401, 423]).toContain(firstOldLogin.response.status());
    assertCleanDiagnostics(diag, 'primary-ui');

    await runBatches(users.slice(1), API_CONCURRENCY, async (user) => {
      const registered = await apiCall(api, 'post', '/auth/register', {
        data: {
          username: user.username,
          password: user.password,
          display_name: user.display_name,
          email: user.email,
          remember: true,
        },
      }, audit, `register ${user.index + 1}`);
      expect(registered.body.user.role).toBe('admin');
      expect(registered.body.user.permissions).toContain('account.manage');
      user.token = registered.body.token;
      audit.created.push(user.username);

      const oldLogin = await apiCall(api, 'post', '/auth/login', { data: { username: user.username, password: user.password } }, audit, `old login ${user.index + 1}`);
      expect(oldLogin.response.status()).toBe(200);

      const changed = await apiCall(api, 'post', '/auth/change-password', {
        headers: authHeaders(user.token),
        data: { new_password: user.newPassword },
      }, audit, `change password ${user.index + 1}`);
      expect(changed.body.changed).toBe(user.username);
      audit.passwordChanged.push(user.username);

      const rejected = await apiCall(api, 'post', '/auth/login', { data: { username: user.username, password: user.password } }, audit, `old password rejected ${user.index + 1}`, [401, 423]);
      expect([401, 423]).toContain(rejected.response.status());

      const newLogin = await loginWithRetry(api, user.username, user.newPassword, audit, `new login ${user.index + 1}`);
      expect(newLogin.response.status()).toBe(200);
      expect(newLogin.body.user.role).toBe('admin');
      user.newToken = newLogin.body.token;
      if (!cleanupToken) cleanupToken = user.newToken;
      return user.username;
    });

    const adminToken = cleanupToken || first.newToken;
    const accounts = await apiCall(api, 'get', '/api/v1/helmet/accounts', { headers: authHeaders(adminToken) }, audit, 'accounts list');
    expect(accounts.response.status()).toBe(200);
    expect(JSON.stringify(accounts.body).toLowerCase()).not.toContain('password_hash');
    expect((accounts.body.items || []).filter((item) => item.username.includes(`helmet_test30_${RUN_ID}`))).toHaveLength(COUNT);

    const cameraId = `helmet-test30-${RUN_ID}`;
    const camera = await apiCall(api, 'post', '/api/v1/helmet/cameras', {
      headers: authHeaders(adminToken),
      data: { camera_id: cameraId, camera_name: 'Helmet Test 30 Camera', source: '0', department: 'Safety' },
    }, audit, 'camera local save');
    expect(camera.response.status()).toBe(200);
    audit.writeChecks.push({ camera: camera.body.camera?.camera_id || cameraId });

    const rejectedCamera = await apiCall(api, 'post', '/api/v1/helmet/cameras', {
      headers: authHeaders(adminToken),
      data: { camera_id: `${cameraId}-remote`, camera_name: 'Rejected Remote', source: 'rtsp://camera.example/live' },
    }, audit, 'camera remote reject', [400]);
    expect(rejectedCamera.response.status()).toBe(400);
    audit.writeChecks.push({ rejectedRemoteSource: true });

    const alerts = await apiCall(api, 'get', '/api/v1/helmet/alerts?days=30&limit=1&mode=compact&include_media=false', { headers: authHeaders(adminToken) }, audit, 'alerts one');
    const alert = (alerts.body.items || [])[0];
    if (alert?.alert_id) {
      const assigned = await apiCall(api, 'post', `/api/v1/helmet/alerts/${encodeURIComponent(alert.alert_id)}/assign`, {
        headers: authHeaders(adminToken),
        data: { assignee: 'helmet-test30-reviewer', note: '30 users lifecycle test' },
      }, audit, 'alert assign');
      expect(assigned.response.status()).toBe(200);
      audit.writeChecks.push({ assignedAlert: alert.alert_id });
    } else {
      audit.writeChecks.push({ assignedAlert: 'skipped-no-alerts' });
    }

    await runBatches(users, UI_CONCURRENCY, async (user) => uiRouteSmoke(browser, user, audit));
  } finally {
    if (cleanupToken) {
      await runBatches(users, API_CONCURRENCY, async (user) => {
        try {
          const deleted = await apiCall(api, 'delete', `/api/v1/helmet/accounts/${encodeURIComponent(user.username)}`, {
            headers: authHeaders(cleanupToken),
          }, audit, `cleanup ${user.index + 1}`, [404]);
          if (deleted.response.status() === 200) cleanup.deleted.push(user.username);
          else if (deleted.response.status() === 404) cleanup.alreadyGone.push(user.username);
          else cleanup.failed.push({ username: user.username, status: deleted.response.status() });
        } catch (error) {
          cleanup.failed.push({ username: user.username, error: error.message });
        }
      });
      const sample = users[0];
      for (let attempt = 1; attempt <= 4; attempt += 1) {
        const gone = await apiCall(api, 'post', '/auth/login', {
          data: { username: sample.username, password: sample.newPassword },
        }, audit, `cleanup verify login rejected ${attempt}`, [401, 423, 500]);
        cleanup.verifyStatus = gone.response.status();
        if ([401, 423].includes(gone.response.status())) {
          cleanup.verifiedGone = true;
          break;
        }
        await delay(500 * attempt);
      }
    } else {
      cleanup.failed.push({ reason: 'no cleanup token available' });
    }
    restoreFile(configPath, configBackup, 'runtime_config', audit);
    await writeAudit(audit, users, cleanup);
    await api.dispose();
  }

  expect(audit.created).toHaveLength(COUNT);
  expect(audit.passwordChanged).toHaveLength(COUNT);
  expect(cleanup.failed, JSON.stringify(cleanup.failed, null, 2)).toEqual([]);
  expect(cleanup.deleted).toHaveLength(COUNT);
  expect(cleanup.verifiedGone).toBeTruthy();
  await testInfo.attach('30-users-audit', { path: path.join(OUTPUT_DIR, 'audit.json'), contentType: 'application/json' });
});
