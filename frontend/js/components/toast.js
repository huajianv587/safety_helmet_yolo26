import { escapeHtml } from '../utils.js?v=1';

const LEVEL_TITLE = {
  success: 'Success',
  error: 'Error',
  warning: 'Warning',
  info: 'Info',
};

function push(level, title, text = '') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const node = document.createElement('div');
  node.className = `toast toast-${level}`;
  node.innerHTML = `
    <div class="toast-title">${escapeHtml(title || LEVEL_TITLE[level] || 'Notice')}</div>
    ${text ? `<div class="toast-text">${escapeHtml(text)}</div>` : ''}
  `;
  container.appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

export const toast = {
  success: (title, text) => push('success', title, text),
  error: (title, text) => push('error', title, text),
  warning: (title, text) => push('warning', title, text),
  info: (title, text) => push('info', title, text),
};

export function initErrorListener() {
  window.addEventListener('unhandledrejection', (event) => {
    const message = event.reason?.message || String(event.reason || '');
    if (message) toast.error('Runtime error', message);
  });
}

