import { assetUrl, isAuthenticated } from './api.js?v=1';
import { pick } from './i18n.js?v=1';

export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function fmt(value, fallback = '--') {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

export function fmtTime(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString();
}

export function fmtPct(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '--';
  return `${number.toFixed(1)}%`;
}

export function statusTone(status) {
  const normalized = String(status || '').toLowerCase();
  if (['remediated', 'confirmed', 'resolved', 'running', 'healthy', 'browser_preview', 'configured', 'ok', 'sent', 'ready', 'synced', 'completed'].includes(normalized)) return 'green';
  if (['pending', 'assigned', 'review_required', 'unresolved', 'queued', 'dry_run', 'warn', 'stale', 'missing', 'skipped', 'disabled'].includes(normalized)) return 'amber';
  if (['false_positive', 'offline', 'error', 'failed', 'rejected', 'invalid'].includes(normalized)) return 'red';
  return '';
}

export function statusLabel(status) {
  const map = {
    pending: pick('待处理', 'Pending'),
    assigned: pick('已转派', 'Assigned'),
    confirmed: pick('已确认', 'Confirmed'),
    remediated: pick('已整改', 'Remediated'),
    false_positive: pick('误报', 'False Positive'),
    ignored: pick('已忽略', 'Ignored'),
    resolved: pick('已识别', 'Resolved'),
    review_required: pick('待复核', 'Review Required'),
    unresolved: pick('未识别', 'Unresolved'),
    browser_preview: pick('浏览器直连', 'Browser Direct'),
    running: pick('运行中', 'Running'),
    healthy: pick('健康', 'Healthy'),
    configured: pick('已配置', 'Configured'),
    offline: pick('离线', 'Offline'),
    error: pick('异常', 'Error'),
    failed: pick('失败', 'Failed'),
    sent: pick('已发送', 'Sent'),
    dry_run: pick('演练', 'Dry Run'),
    ready: pick('就绪', 'Ready'),
    warn: pick('预警', 'Warn'),
    missing: pick('缺失', 'Missing'),
    invalid: pick('无效', 'Invalid'),
    skipped: pick('跳过', 'Skipped'),
    synced: pick('已同步', 'Synced'),
    completed: pick('已完成', 'Completed'),
    disabled: pick('已禁用', 'Disabled'),
  };
  return map[String(status || '')] || fmt(status);
}

export function badge(status, label = '') {
  const rendered = label || statusLabel(status);
  return `<span class="badge ${statusTone(status)}">${escapeHtml(rendered)}</span>`;
}

export function metricCard(label, value, note, tone = '') {
  return `<div class="metric-card ${tone}">
    <div class="metric-label">${escapeHtml(label)}</div>
    <div class="metric-value">${escapeHtml(value)}</div>
    <div class="metric-note">${escapeHtml(note)}</div>
  </div>`;
}

export function emptyState(title, text = '') {
  return `<div class="empty-state">
    <div>
      <div class="empty-state__title">${escapeHtml(title)}</div>
      ${text ? `<div>${escapeHtml(text)}</div>` : ''}
    </div>
  </div>`;
}

export function pageHeader(kicker, title, copy, actionHtml = '') {
  return `<div class="page-header">
    <div>
      <div class="page-header__kicker">${escapeHtml(kicker)}</div>
      <div class="page-header__title">${escapeHtml(title)}</div>
      <div class="page-header__copy">${escapeHtml(copy)}</div>
    </div>
    <div class="page-actions">${actionHtml}</div>
  </div>`;
}

export function table(headers, rows, rowRenderer) {
  if (!rows || !rows.length) return emptyState(pick('暂无可展示记录', 'No records to display'));
  return `<div class="table-wrap"><table class="table">
    <thead><tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(rowRenderer).join('')}</tbody>
  </table></div>`;
}

export function mediaSrc(value) {
  return assetUrl(value);
}

function mediaFallbackText(state) {
  const normalized = String(state || '').toLowerCase();
  if (normalized === 'blocked') return pick('证据访问受保护', 'Evidence access is protected');
  if (normalized === 'remote_url') return pick('远程证据暂不可达', 'Remote evidence is temporarily unavailable');
  return pick('证据文件缺失', 'Evidence file is missing');
}

export function mediaImage(value, alt, options = {}) {
  const src = mediaSrc(value);
  const state = options.state || (src ? 'available' : 'missing');
  const caption = options.caption || pick('仅保留事件记录，重新采集后可回看。', 'Only the event record remains. Capture again to review media.');
  const fallback = `<div class="media-fallback">
    <div>
      <div class="media-fallback__title">${escapeHtml(mediaFallbackText(state))}</div>
      <div class="media-fallback__copy">${escapeHtml(caption)}</div>
    </div>
  </div>`;
  if (!src || ['missing', 'blocked', 'remote_url'].includes(String(state).toLowerCase())) return fallback;
  return `<div class="media-shell">
    <img src="${escapeHtml(src)}" alt="${escapeHtml(alt || 'evidence image')}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid';">
    <div class="media-fallback" style="display:none">
      <div>
        <div class="media-fallback__title">${escapeHtml(mediaFallbackText(state))}</div>
        <div class="media-fallback__copy">${escapeHtml(caption)}</div>
      </div>
    </div>
  </div>`;
}

export function markPageReady(container, name) {
  container.setAttribute('data-page-ready', name);
  container.classList.add('page-ready');
}

export function downloadCsv(filename, rows) {
  if (!rows || !rows.length) return;
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(',')];
  rows.forEach((row) => {
    lines.push(headers.map((key) => {
      const raw = String(row[key] ?? '').replace(/"/g, '""');
      return `"${raw}"`;
    }).join(','));
  });
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function renderChart(el, option) {
  if (!el || !window.echarts) {
    if (el) el.innerHTML = emptyState(pick('图表引擎不可用', 'Chart renderer unavailable'));
    return null;
  }
  const chart = window.echarts.init(el, null, { renderer: 'canvas' });
  chart.setOption(option);
  const onResize = () => chart.resize();
  window.addEventListener('resize', onResize);
  return {
    chart,
    destroy: () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
    },
  };
}

export function writeGuardMessage() {
  return isAuthenticated()
    ? ''
    : pick('当前为访客只读模式。登录后才能修改真实配置。', 'Guest mode is read-only. Login before changing live configuration.');
}
