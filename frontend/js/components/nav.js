import { getAuthUser } from '../api.js?v=1';
import { ROUTES } from '../router.js?v=1';
import { t, onLangChange } from '../i18n.js?v=1';

const ICONS = {
  grid: '<path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  camera: '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
  chart: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  bell: '<path d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5"/><path d="M10 21a2 2 0 0 0 4 0"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  settings: '<path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.36a1.7 1.7 0 0 0-1 .57 1.7 1.7 0 0 0-.43 1.07V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.59 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.64 15a1.7 1.7 0 0 0-.57-1 1.7 1.7 0 0 0-1.07-.43H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.59-1.11 1.7 1.7 0 0 0-.34-1.87l-.06-.06A2 2 0 1 1 7.11 3.7l.06.06A1.7 1.7 0 0 0 9 4.64c.39-.16.73-.36 1-.57A1.7 1.7 0 0 0 10.43 3V3a2 2 0 1 1 4 0v.09c0 .43.16.82.43 1.07.27.21.61.41 1 .57a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.36 9c.16.39.36.73.57 1 .25.27.64.43 1.07.43H21a2 2 0 1 1 0 4h-.09c-.43 0-.82.16-1.07.43-.21.27-.41.61-.57 1z"/>',
  command: '<path d="M18 3h3v3"/><path d="M3 21l9-9"/><path d="M3 9l6 6"/><path d="M15 15h6"/>',
};

function icon(name) {
  const path = ICONS[name] || ICONS.grid;
  return `<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

export function renderNav() {
  const container = document.getElementById('nav-links');
  if (!container) return;
  const current = (window.location.hash.slice(1) || '/dashboard').split('?')[0];
  const user = getAuthUser();
  const allowed = new Set(Array.isArray(user.routes) ? user.routes : []);
  const groups = {};

  Object.entries(ROUTES).forEach(([path, config]) => {
    if (config.hidden || config.noShell || !allowed.has(path)) return;
    const group = config.group || 'ops';
    groups[group] = groups[group] || [];
    groups[group].push({ path, config });
  });

  const groupLabels = {
    platform: 'nav.platform',
    ops: 'nav.ops',
    config: 'nav.config',
    operations: 'nav.operations',
  };

  container.innerHTML = Object.entries(groups).map(([group, items]) => {
    const links = items.map(({ path, config }) => `<a class="nav-item ${path === current ? 'active' : ''}" href="#${path}" data-path="${path}">
      ${icon(config.icon)}
      <span>${t(config.labelKey)}</span>
    </a>`).join('');
    return `<div class="nav-section-label">${t(groupLabels[group] || group)}</div>${links}`;
  }).join('');
}

export function updateHealth(online) {
  const dot = document.getElementById('health-dot');
  const text = document.getElementById('health-text');
  if (!dot || !text) return;
  dot.className = `status-dot ${online ? 'online' : 'degraded'}`;
  text.textContent = online ? t('common.backend_online') : t('common.backend_offline');
}

function syncHealthLabel() {
  const dot = document.getElementById('health-dot');
  if (!dot) return;
  if (dot.classList.contains('online')) updateHealth(true);
  else if (dot.classList.contains('degraded')) updateHealth(false);
  else {
    const text = document.getElementById('health-text');
    if (text) text.textContent = t('common.connecting');
  }
}

export function initNav() {
  renderNav();
  syncHealthLabel();
  window.addEventListener('route-change', () => {
    renderNav();
    requestAnimationFrame(syncHealthLabel);
  });
  window.addEventListener('auth-change', renderNav);
  onLangChange(() => {
    renderNav();
    syncHealthLabel();
  });
}
