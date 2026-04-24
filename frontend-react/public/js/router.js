import { clearAuth, getAuthToken, getAuthUser } from './api.js?v=1';
import { t, onLangChange } from './i18n.js?v=1';

const VER = 'v2';

export const ROUTES = {
  '/login': { module: () => import(`./pages/login.js?${VER}`), labelKey: 'page.login', icon: 'lock', group: 'auth', hidden: true, noShell: true },
  '/register': { module: () => import(`./pages/register.js?${VER}`), labelKey: 'page.register', icon: 'users', group: 'auth', hidden: true, noShell: true },
  '/dashboard': { module: () => import(`./pages/dashboard.js?${VER}`), labelKey: 'page.dashboard', icon: 'grid', group: 'platform' },
  '/review': { module: () => import(`./pages/review.js?${VER}`), labelKey: 'page.review', icon: 'shield', group: 'ops' },
  '/cameras': { module: () => import(`./pages/cameras.js?${VER}`), labelKey: 'page.cameras', icon: 'camera', group: 'ops' },
  '/reports': { module: () => import(`./pages/reports.js?${VER}`), labelKey: 'page.reports', icon: 'chart', group: 'ops' },
  '/hard-cases': { module: () => import(`./pages/hard-cases.js?${VER}`), labelKey: 'page.hard_cases', icon: 'database', group: 'ops' },
  '/config': { module: () => import(`./pages/config.js?${VER}`), labelKey: 'page.config', icon: 'settings', group: 'config' },
  '/operations': { module: () => import(`./pages/operations.js?${VER}`), labelKey: 'page.operations', icon: 'command', group: 'operations' },
  '/notifications': { module: () => import(`./pages/notifications.js?${VER}`), labelKey: 'page.notifications', icon: 'bell', group: 'operations', hidden: true },
  '/access-admin': { module: () => import(`./pages/access-admin.js?${VER}`), labelKey: 'page.access_admin', icon: 'users', group: 'operations', hidden: true },
};

const DEFAULT = '/dashboard';
const AUTH_ROUTES = new Set(['/login', '/register']);

function normalizePath() {
  const raw = window.location.hash.slice(1) || DEFAULT;
  const path = raw.split('?')[0] || DEFAULT;
  return ROUTES[path] ? path : DEFAULT;
}

function currentHash() {
  return window.location.hash.slice(1) || DEFAULT;
}

class Router {
  constructor() {
    this._container = null;
    this._mod = null;
    this._current = null;
    this._navId = 0;
  }

  init(container) {
    this._container = container;
    window.addEventListener('hashchange', () => this._go());
    onLangChange(() => {
      this._applyTitle(this.getCurrentPath());
      this.refresh();
    });
    this._go();
  }

  async navigate(path) {
    window.location.hash = `#${path}`;
  }

  async refresh() {
    if (!this._container) return;
    await this._go();
  }

  getCurrentPath() {
    return this._current || normalizePath();
  }

  getRoutes() {
    return ROUTES;
  }

  logout() {
    clearAuth();
    window.location.hash = `#${DEFAULT}`;
  }

  _applyTitle(path) {
    const config = ROUTES[path];
    const titleEl = document.getElementById('page-title');
    if (titleEl && config) titleEl.textContent = t(config.labelKey);
  }

  async _go() {
    const navId = ++this._navId;
    const path = normalizePath();
    const config = ROUTES[path];
    const raw = currentHash();

    if (path === '/notifications') {
      window.location.hash = '#/operations?section=notifications';
      return;
    }
    if (path === '/access-admin') {
      window.location.hash = '#/operations?section=access-admin';
      return;
    }

    if (AUTH_ROUTES.has(path) && getAuthToken()) {
      window.location.hash = `#${DEFAULT}`;
      return;
    }

    const user = getAuthUser();
    const allowedRoutes = Array.isArray(user.routes) ? user.routes : [];
    if (!AUTH_ROUTES.has(path) && !allowedRoutes.includes(path)) {
      window.location.hash = `#${DEFAULT}`;
      return;
    }

    if (this._mod?.destroy) await this._mod.destroy();
    this._current = path;
    this._applyTitle(path);
    document.querySelector('.app-shell')?.classList.toggle('auth-mode', Boolean(config.noShell));
    window.dispatchEvent(new CustomEvent('route-change', { detail: { path, raw } }));

    this._container.innerHTML = '';
    const pageHost = document.createElement('div');
    pageHost.className = 'route-host';
    this._container.appendChild(pageHost);
    this._container.classList.remove('page-ready');
    try {
      const mod = await config.module();
      if (navId !== this._navId) return;
      this._mod = mod;
      await this._mod.render(pageHost);
      if (navId !== this._navId) {
        pageHost.remove();
        return;
      }
      requestAnimationFrame(() => this._container.classList.add('page-ready'));
    } catch (error) {
      if (navId !== this._navId) return;
      console.error(error);
      pageHost.innerHTML = `<div class="empty-state"><div><div class="empty-state__title">${t('common.page_load_failed')}</div><div>${error.message}</div></div></div>`;
      this._container.classList.add('page-ready');
    }
  }
}

export const router = new Router();
