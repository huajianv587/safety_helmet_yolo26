import { api, getAuthUser } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import { emptyState, escapeHtml, fmt, fmtTime, markPageReady, mediaImage, metricCard, pageHeader, table } from '../utils.js?v=1';

function evidenceGrid(rows) {
  const evidenceRows = rows.slice(0, 6);
  if (!evidenceRows.length) return emptyState(pick('暂无可视化回流证据', 'No visual feedback evidence yet'));
  return `<div class="evidence-grid">${evidenceRows.map((item) => `<div class="evidence-item">
    ${mediaImage(item.snapshot_display_url, pick('难例证据', 'Hard case evidence'), { state: item.snapshot_media_state })}
    <div class="evidence-caption">${escapeHtml(item.event_no || item.alert_id || '--')}<br>${escapeHtml(item.case_type || '--')}</div>
  </div>`).join('')}</div>`;
}

function shell() {
  const user = getAuthUser();
  const actions = (user.routes || []).includes('/operations')
    ? `<a class="btn btn-ghost" href="#/operations?section=model-feedback">${pick('前往模型反馈', 'Open Model Feedback')}</a>`
    : '';
  return pageHeader(
    'MODEL FEEDBACK',
    pick('回流池', 'Hard Cases'),
    pick('沉淀误报和难例，为模型与规则优化提供输入。', 'Collect false positives and hard cases for model and policy improvement.'),
    actions,
  );
}

export async function render(container) {
  container.innerHTML = `${shell()}${emptyState(pick('正在加载回流池', 'Loading hard cases'))}`;
  try {
    const response = await api.hardCases.list({ limit: 50, offset: 0, include_media: true });
    const rows = response.items || [];
    const metrics = response.metrics || {};
    container.innerHTML = `${shell()}
      <section class="metric-grid">
        ${metricCard(pick('回流总量', 'Total Cases'), fmt(metrics.total), pick('当前回流池样本数', 'Feedback pool size'))}
        ${metricCard(pick('涉及摄像头', 'Cameras'), fmt(metrics.cameras), pick('覆盖设备数量', 'Covered cameras'))}
        ${metricCard(pick('最近 7 天', 'Last 7 Days'), fmt(metrics.recent_7d), pick('近期新增样本', 'Recent additions'), 'warning')}
      </section>
      <section class="two-col">
        <div class="card"><div class="card-header"><div><div class="card-title">${pick('证据回看', 'Evidence Review')}</div></div></div><div class="card-body">${evidenceGrid(rows)}</div></div>
        <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('回流记录', 'Feedback Records')}</div></div></div><div class="table-body">${table(
          [pick('事件', 'Event'), pick('类型', 'Type'), pick('摄像头', 'Camera'), pick('部门', 'Department'), pick('时间', 'Time')],
          rows,
          (item) => `<tr>
            <td>${escapeHtml(item.event_no || item.alert_id || '--')}</td>
            <td>${escapeHtml(item.case_type || '--')}</td>
            <td>${escapeHtml(item.camera_name || item.camera_id || '--')}</td>
            <td>${escapeHtml(item.department || '--')}</td>
            <td>${escapeHtml(fmtTime(item.created_at))}</td>
          </tr>`,
        )}</div></div>
      </section>`;
    markPageReady(container, 'hard-cases');
  } catch (error) {
    container.innerHTML = `${shell()}${emptyState(pick('回流池接口暂不可用', 'Hard-case API unavailable'), error.message)}`;
    markPageReady(container, 'hard-cases');
  }
}
