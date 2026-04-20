import { api, clearAuth, getAuthUser, hydrateSession, isAuthenticated } from './api.js?v=1';
import { router } from './router.js?v=1';
import { initNav, renderNav, updateHealth } from './components/nav.js?v=1';
import { toast, initErrorListener } from './components/toast.js?v=1';
import { getLang, setLang, onLangChange, t } from './i18n.js?v=1';

function getTheme() {
  return localStorage.getItem('helmet-theme') || 'dark';
}

function setTheme(mode) {
  localStorage.setItem('helmet-theme', mode);
  document.body.classList.toggle('light', mode === 'light');
  const button = document.getElementById('theme-toggle-btn');
  if (button) button.textContent = mode === 'light' ? 'LIGHT' : 'DARK';
  window.dispatchEvent(new CustomEvent('theme-change', { detail: { mode } }));
}

function buildTopbarActions() {
  const actions = document.getElementById('header-actions');
  if (!actions) return;

  const user = getAuthUser();
  const lang = getLang();
  const theme = getTheme();
  const signedIn = isAuthenticated();
  const themeLabel = theme === 'light' ? 'LIGHT' : 'DARK';
  const zhLabel = 'ZH';
  const userLabel = signedIn ? (user.display_name || user.username) : t('auth.guest');

  actions.innerHTML = `
    <div class="topbar-control-group" aria-label="${t('common.display_controls')}">
      <button class="topbar-chip active" id="theme-toggle-btn" title="${t('common.toggle_theme')}">${themeLabel}</button>
      <button class="topbar-chip ${lang === 'zh' ? 'active' : ''}" id="tb-lang-zh">${zhLabel}</button>
      <button class="topbar-chip ${lang === 'en' ? 'active' : ''}" id="tb-lang-en">EN</button>
    </div>
    <div class="topbar-user">
      <span class="topbar-chip">${userLabel}</span>
      ${signedIn
        ? `<button class="topbar-chip" id="btn-logout">${t('auth.logout')}</button>`
        : `<a class="topbar-chip topbar-chip--primary" href="#/login">${t('auth.login_to_configure')}</a><a class="topbar-chip" href="#/register">${t('auth.register')}</a>`}
    </div>
  `;

  actions.querySelector('#theme-toggle-btn')?.addEventListener('click', () => {
    setTheme(getTheme() === 'dark' ? 'light' : 'dark');
    buildTopbarActions();
  });
  actions.querySelector('#tb-lang-zh')?.addEventListener('click', () => setLang('zh'));
  actions.querySelector('#tb-lang-en')?.addEventListener('click', () => setLang('en'));
  actions.querySelector('#btn-logout')?.addEventListener('click', () => {
    clearAuth();
    toast.info(t('auth.logout'));
    window.location.hash = '#/dashboard';
    buildTopbarActions();
    renderNav();
  });
}

async function updateBackendHealth(showToast = false) {
  try {
    await api.health();
    updateHealth(true);
    if (showToast) toast.success(t('common.backend_online'));
    return true;
  } catch (error) {
    updateHealth(false);
    if (showToast) toast.error(t('common.backend_offline'), error.message);
    return false;
  }
}

function initMobileNav() {
  const open = () => document.body.classList.add('sidebar-open');
  const close = () => document.body.classList.remove('sidebar-open');
  document.getElementById('mobile-menu-btn')?.addEventListener('click', open);
  document.getElementById('sidebar-scrim')?.addEventListener('click', close);
  window.addEventListener('route-change', close);
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  });
}

async function init() {
  setTheme(getTheme());
  initErrorListener();
  await hydrateSession();
  initNav();
  initMobileNav();
  buildTopbarActions();
  onLangChange(() => {
    buildTopbarActions();
    updateHealth(document.getElementById('health-dot')?.classList.contains('online'));
  });
  window.addEventListener('auth-change', () => {
    buildTopbarActions();
    renderNav();
  });
  router.init(document.getElementById('app-root'));
  window.addEventListener('theme-change', () => router.refresh());
  await updateBackendHealth(false);
  setInterval(() => updateBackendHealth(false), 30000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
