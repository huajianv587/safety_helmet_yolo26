import { api, isAuthenticated } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import {
  badge,
  emptyState,
  escapeHtml,
  fmt,
  fmtTime,
  markPageReady,
  mediaImage,
  metricCard,
  pageHeader,
  statusLabel,
  table,
  writeGuardMessage,
} from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

const STATUS_FILTERS = [
  { id: 'all', label: () => pick('全部', 'All'), statuses: '' },
  { id: 'pending', label: () => pick('待处理', 'Pending'), statuses: 'pending' },
  { id: 'assigned', label: () => pick('已转派', 'Assigned'), statuses: 'assigned' },
  { id: 'closed', label: () => pick('已整改', 'Remediated'), statuses: 'remediated,confirmed' },
  { id: 'false', label: () => pick('误报 / 忽略', 'False / Ignored'), statuses: 'false_positive,ignored' },
];

const REVIEW_TABS = [
  { id: 'queue', label: () => pick('队列', 'Queue') },
  { id: 'detail', label: () => pick('详情', 'Detail') },
  { id: 'history', label: () => pick('处理记录', 'History') },
];

const ACTION_PAGE_SIZE = 15;

let state = {
  alerts: [],
  people: [],
  selected: null,
  total: 0,
  offset: 0,
  limit: 10,
  filter: 'all',
  identityFilter: '',
  detail: null,
  actionActor: '',
  actionPage: 0,
  mobileTab: 'queue',
};

function isMobileView() {
  return window.matchMedia('(max-width: 860px)').matches;
}

function activeStatusFilter() {
  return STATUS_FILTERS.find((item) => item.id === state.filter) || STATUS_FILTERS[0];
}

function selectedAlert() {
  return state.alerts.find((item) => item.alert_id === state.selected) || state.alerts[0] || null;
}

function actionActors(detail) {
  return Array.from(new Set((detail?.actions || []).map((item) => String(item.actor || '').trim()).filter(Boolean)));
}

function filteredActions(detail) {
  const rows = detail?.actions || [];
  if (!state.actionActor) return rows;
  return rows.filter((item) => String(item.actor || '') === state.actionActor);
}

function pagedActions(detail) {
  const rows = filteredActions(detail);
  const start = state.actionPage * ACTION_PAGE_SIZE;
  return {
    rows: rows.slice(start, start + ACTION_PAGE_SIZE),
    total: rows.length,
    start,
  };
}

function renderQueueFilters() {
  return `<div class="status-filter-row" data-review-filters>
    ${STATUS_FILTERS.map((item) => `<button class="status-filter ${item.id === state.filter ? 'active' : ''}" data-status-filter="${item.id}" type="button">${escapeHtml(item.label())}</button>`).join('')}
    ${state.identityFilter ? `<button class="status-filter active" data-identity-clear type="button">${escapeHtml(`${pick('身份', 'Identity')}: ${statusLabel(state.identityFilter)}`)} ×</button>` : ''}
  </div>`;
}

function renderQueueTable() {
  return table(
    [pick('事件', 'Event'), pick('摄像头', 'Camera'), pick('人员', 'Person'), pick('状态', 'Status'), pick('时间', 'Time')],
    state.alerts,
    (item) => `<tr data-alert-id="${escapeHtml(item.alert_id)}" class="${item.alert_id === state.selected ? 'selected' : ''}" style="cursor:pointer">
      <td>${escapeHtml(item.event_no || item.alert_id || '--')}</td>
      <td>${escapeHtml(item.camera_name || item.camera_id || '--')}</td>
      <td>${escapeHtml(item.person_name || 'Unknown')}</td>
      <td>${badge(item.status)}</td>
      <td>${escapeHtml(fmtTime(item.created_at))}</td>
    </tr>`,
  );
}

function renderQueuePager() {
  if (state.total <= state.limit) return '';
  const start = state.total ? state.offset + 1 : 0;
  const end = Math.min(state.offset + state.alerts.length, state.total);
  return `<div class="review-pager">
    <button class="btn btn-ghost btn-sm" id="review-prev-page" ${state.offset <= 0 ? 'disabled' : ''}>${pick('上一页', 'Prev')}</button>
    <span>${escapeHtml(`${start}-${end} / ${state.total}`)}</span>
    <button class="btn btn-ghost btn-sm" id="review-next-page" ${end >= state.total ? 'disabled' : ''}>${pick('下一页', 'Next')}</button>
  </div>`;
}

function loginGuard() {
  const text = writeGuardMessage();
  return text ? `<div class="guard-note">${escapeHtml(text)}</div>` : '';
}

function statusFilterIdFor(status) {
  const normalized = String(status || '');
  if (normalized === 'pending') return 'pending';
  if (normalized === 'assigned') return 'assigned';
  if (['remediated', 'confirmed'].includes(normalized)) return 'closed';
  if (['false_positive', 'ignored'].includes(normalized)) return 'false';
  return 'all';
}

function videoCard(url, stateValue) {
  if (!url || ['missing', 'blocked', 'remote_url'].includes(String(stateValue || '').toLowerCase())) {
    return emptyState(pick('暂无可回放视频', 'No video clip available'));
  }
  return `<video class="case-video" src="${escapeHtml(url)}" controls preload="metadata"></video>`;
}

function renderActionHistory(detail) {
  const actors = actionActors(detail);
  const page = pagedActions(detail);
  const pageCount = Math.max(1, Math.ceil(page.total / ACTION_PAGE_SIZE));
  const currentPage = Math.min(pageCount, state.actionPage + 1);
  return `<div class="table-panel review-history-panel">
    <div class="table-header">
      <div>
        <div class="table-title">${pick('处理记录', 'Action History')}</div>
        <div class="table-sub">${pick('整块主表展示，可按操作者筛选和分页。', 'One wide table with actor filters and pagination.')}</div>
      </div>
    </div>
    <div class="table-body">
      <div class="status-filter-row review-actor-row">
        <button class="status-filter ${state.actionActor ? '' : 'active'}" data-action-actor="" type="button">${pick('全部操作者', 'All Actors')}</button>
        ${actors.map((actor) => `<button class="status-filter ${actor === state.actionActor ? 'active' : ''}" data-action-actor="${escapeHtml(actor)}" type="button">${escapeHtml(actor)}</button>`).join('')}
      </div>
      <div class="review-pager">
        <span>${escapeHtml(`${pick('第', 'Page')} ${currentPage} / ${pageCount}`)}</span>
        <div class="inline-actions">
          <button class="btn btn-ghost btn-sm" id="history-prev-page" ${state.actionPage <= 0 ? 'disabled' : ''}>${pick('上一页', 'Prev')}</button>
          <button class="btn btn-ghost btn-sm" id="history-next-page" ${(state.actionPage + 1) >= pageCount ? 'disabled' : ''}>${pick('下一页', 'Next')}</button>
        </div>
      </div>
      ${page.rows.length ? `<div class="review-history-window">
        <table class="table table-fixed action-history-table">
          <thead>
            <tr>
              <th>${escapeHtml(pick('动作', 'Action'))}</th>
              <th>${escapeHtml(pick('操作者', 'Actor'))}</th>
              <th>${escapeHtml(pick('备注', 'Note'))}</th>
              <th>${escapeHtml(pick('时间', 'Time'))}</th>
            </tr>
          </thead>
          <tbody>
            ${page.rows.map((item) => `<tr>
              <td>${escapeHtml(item.action_type || '--')}</td>
              <td>${escapeHtml(item.actor || '--')}</td>
              <td class="table-wrap-cell">${escapeHtml(item.note || '--')}</td>
              <td>${escapeHtml(fmtTime(item.created_at))}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>` : emptyState(pick('当前筛选下没有处理记录', 'No action history for this filter'))}
    </div>
  </div>`;
}

function renderNotificationLog(detail) {
  return `<div class="table-panel review-secondary-panel">
    <div class="table-header">
      <div>
        <div class="table-title">${pick('通知记录', 'Notification Log')}</div>
        <div class="table-sub">${pick('次级摘要面板，保留链路可见性。', 'Secondary summary panel for delivery visibility.')}</div>
      </div>
    </div>
    <div class="table-body">${table(
      [pick('接收人', 'Recipient'), pick('通道', 'Channel'), pick('状态', 'Status'), pick('时间', 'Time')],
      detail?.notifications || [],
      (item) => `<tr><td>${escapeHtml(item.recipient || '--')}</td><td>${escapeHtml(item.channel || '--')}</td><td>${badge(item.status)}</td><td>${escapeHtml(fmtTime(item.created_at))}</td></tr>`,
    )}</div>
  </div>`;
}

function renderSelectionSummary(alert) {
  if (!alert) return emptyState(pick('暂无工单', 'No cases'));
  return `<div class="detail-list">
    <div class="detail-item"><div class="detail-key">${pick('摄像头', 'Camera')}</div><div class="detail-value">${escapeHtml(alert.camera_name || '--')}</div></div>
    <div class="detail-item"><div class="detail-key">${pick('人员', 'Person')}</div><div class="detail-value">${escapeHtml(alert.person_name || 'Unknown')}</div></div>
    <div class="detail-item"><div class="detail-key">${pick('状态', 'Status')}</div><div class="detail-value"><button class="chip-button" data-chip-status="${escapeHtml(statusFilterIdFor(alert.status))}" type="button">${badge(alert.status)}</button></div></div>
    <div class="detail-item"><div class="detail-key">${pick('身份', 'Identity')}</div><div class="detail-value"><button class="chip-button" data-chip-identity="${escapeHtml(alert.identity_status || '')}" type="button">${badge(alert.identity_status)}</button></div></div>
  </div>`;
}

function renderDossier(detail) {
  const alert = detail?.alert || selectedAlert();
  if (!alert) return emptyState(pick('请选择一个工单', 'Select a case'));
  const peopleOptions = [`<option value="">${pick('保持当前人员', 'Keep current person')}</option>`].concat(
    state.people.map((person) => `<option value="${escapeHtml(person.person_id)}">${escapeHtml([person.name, person.employee_id, person.department].filter(Boolean).join(' / '))}</option>`),
  ).join('');
  const writeLabel = isAuthenticated() ? pick('提交', 'Submit') : pick('登录后提交', 'Login to Submit');

  return `<div class="panel-stack">
    <div class="case-layout">
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${pick('现场证据', 'Evidence Stack')}</div>
            <div class="card-sub">${pick('截图、人脸、工牌、整改截图和视频剪辑集中查看。', 'Snapshots, crops, remediation evidence, and video clips together.')}</div>
          </div>
        </div>
        <div class="card-body">
          <div class="case-media">${mediaImage(alert.snapshot_display_url, pick('现场截图', 'Scene snapshot'), { state: alert.snapshot_media_state })}</div>
          <div class="three-col" style="margin-top:12px">
            <div class="case-media">${mediaImage(alert.face_crop_display_url, pick('人脸裁剪', 'Face crop'), { state: alert.face_crop_media_state, caption: pick('当前没有可用的人脸裁剪。', 'No face crop is available.') })}</div>
            <div class="case-media">${mediaImage(alert.badge_crop_display_url, pick('工牌裁剪', 'Badge crop'), { state: alert.badge_crop_media_state, caption: pick('当前没有可用的工牌裁剪。', 'No badge crop is available.') })}</div>
            <div class="case-media">${mediaImage(alert.remediation_snapshot_display_url, pick('整改截图', 'Remediation snapshot'), { state: alert.remediation_snapshot_media_state, caption: pick('当前没有上传整改截图。', 'No remediation snapshot uploaded.') })}</div>
          </div>
          <div class="card" style="margin-top:12px">
            <div class="card-header"><div><div class="card-title">${pick('视频剪辑', 'Violation Clip')}</div></div></div>
            <div class="card-body">${videoCard(alert.clip_display_url, alert.clip_media_state)}</div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${pick('案件画像', 'Case Dossier')}</div>
            <div class="card-sub">${pick('当前状态、身份来源和位置摘要。', 'Current state, identity source, and location summary.')}</div>
          </div>
        </div>
        <div class="card-body">
          <div class="case-chip-row">
            <button class="chip-button" data-chip-status="${escapeHtml(statusFilterIdFor(alert.status))}" type="button">${badge(alert.status)}</button>
            <button class="chip-button" data-chip-identity="${escapeHtml(alert.identity_status || '')}" type="button">${badge(alert.identity_status)}</button>
            <span class="badge">${escapeHtml(alert.camera_name || '--')}</span>
          </div>
          <div class="detail-list">
            <div class="detail-item"><div class="detail-key">${pick('事件编号', 'Event')}</div><div class="detail-value">${escapeHtml(alert.event_no || alert.alert_id || '--')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('人员', 'Person')}</div><div class="detail-value">${escapeHtml(alert.person_name || 'Unknown')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('工号', 'Employee')}</div><div class="detail-value">${escapeHtml(alert.employee_id || '--')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('身份来源', 'Identity Source')}</div><div class="detail-value">${escapeHtml(alert.identity_source || '--')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('身份置信度', 'Identity Confidence')}</div><div class="detail-value">${escapeHtml(fmt(alert.identity_confidence))}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('工牌文本', 'Badge Text')}</div><div class="detail-value">${escapeHtml(alert.badge_text || '--')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('工牌置信度', 'Badge Confidence')}</div><div class="detail-value">${escapeHtml(fmt(alert.badge_confidence))}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('部门', 'Department')}</div><div class="detail-value">${escapeHtml(alert.department || '--')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('地点', 'Location')}</div><div class="detail-value">${escapeHtml([alert.site_name, alert.building_name, alert.floor_name, alert.zone_name].filter(Boolean).join(' / ') || alert.location || '--')}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('时间', 'Time')}</div><div class="detail-value">${escapeHtml(fmtTime(alert.created_at))}</div></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${pick('转派', 'Assignment')}</div>
            <div class="card-sub">${pick('把工单交给明确责任人。', 'Route the case to an owner.')}</div>
          </div>
        </div>
        <div class="card-body">
          ${loginGuard()}
          <form id="assign-form" class="form-grid one">
            <label class="form-row"><span class="form-label">${pick('责任人', 'Assignee')}</span><input class="form-input" id="assignee"></label>
            <label class="form-row"><span class="form-label">${pick('责任人邮箱', 'Assignee Email')}</span><input class="form-input" id="assignee-email"></label>
            <label class="form-row"><span class="form-label">${pick('备注', 'Note')}</span><textarea class="form-textarea" id="assign-note"></textarea></label>
            <button class="btn btn-primary" id="assign-case-btn" type="submit">${writeLabel}</button>
          </form>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${pick('状态流转', 'Case Resolution')}</div>
            <div class="card-sub">${pick('更新状态、修正人员并上传整改证据。', 'Update status, correct people, and upload remediation evidence.')}</div>
          </div>
        </div>
        <div class="card-body">
          ${loginGuard()}
          <form id="status-form" class="form-grid one">
            <label class="form-row">
              <span class="form-label">${pick('新状态', 'New Status')}</span>
              <select class="form-select" id="new-status">
                ${['pending', 'assigned', 'confirmed', 'remediated', 'false_positive', 'ignored'].map((item) => `<option value="${item}" ${item === alert.status ? 'selected' : ''}>${escapeHtml(statusLabel(item))}</option>`).join('')}
              </select>
            </label>
            <label class="form-row"><span class="form-label">${pick('人工确认人员', 'Resolved Person')}</span><select class="form-select" id="person-id">${peopleOptions}</select></label>
            <label class="form-row"><span class="form-label">${pick('处置备注', 'Resolution Note')}</span><textarea class="form-textarea" id="status-note"></textarea></label>
            <label class="form-row"><span class="form-label">${pick('整改截图', 'Remediation Snapshot')}</span><input class="form-input" id="remediation-file" type="file" accept="image/png,image/jpeg"></label>
            <button class="btn btn-primary" id="update-case-btn" type="submit">${writeLabel}</button>
          </form>
        </div>
      </div>
    </div>
    ${renderNotificationLog(detail)}
  </div>`;
}

async function fetchSelectedDetail() {
  const alert = selectedAlert();
  if (!alert) return null;
  try {
    return await api.alerts.get(alert.alert_id);
  } catch (error) {
    toast.warning(pick('详情暂不可用', 'Detail unavailable'), error.message);
    return { alert, actions: [], notifications: [] };
  }
}

function requireLoginForWrite() {
  if (isAuthenticated()) return true;
  toast.warning(
    pick('请先登录', 'Login required'),
    pick('访客模式只能浏览复核信息，不能写入处置结果。', 'Guest mode can inspect cases but cannot write review results.'),
  );
  window.location.hash = '#/login';
  return false;
}

function bindQueueFilters(container) {
  container.querySelectorAll('[data-status-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      state.filter = button.getAttribute('data-status-filter') || 'all';
      state.offset = 0;
      state.selected = null;
      render(container);
    });
  });
  container.querySelector('[data-identity-clear]')?.addEventListener('click', () => {
    state.identityFilter = '';
    state.offset = 0;
    render(container);
  });
  container.querySelectorAll('[data-chip-status]').forEach((button) => {
    button.addEventListener('click', () => {
      state.filter = button.getAttribute('data-chip-status') || 'all';
      state.offset = 0;
      render(container);
    });
  });
  container.querySelectorAll('[data-chip-identity]').forEach((button) => {
    button.addEventListener('click', () => {
      state.identityFilter = button.getAttribute('data-chip-identity') || '';
      state.offset = 0;
      render(container);
    });
  });
}

function bindActionHistory(container) {
  container.querySelectorAll('[data-action-actor]').forEach((button) => {
    button.addEventListener('click', async () => {
      state.actionActor = button.getAttribute('data-action-actor') || '';
      state.actionPage = 0;
      await redraw(container);
    });
  });
  container.querySelector('#history-prev-page')?.addEventListener('click', async () => {
    state.actionPage = Math.max(0, state.actionPage - 1);
    await redraw(container);
  });
  container.querySelector('#history-next-page')?.addEventListener('click', async () => {
    state.actionPage += 1;
    await redraw(container);
  });
}

function bindMobileTabs(container) {
  container.querySelectorAll('[data-review-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      state.mobileTab = button.getAttribute('data-review-tab') || 'queue';
      redraw(container);
    });
  });
}

function reviewTabs() {
  return `<div class="review-mobile-tabs">
    ${REVIEW_TABS.map((tab) => `<button class="status-filter ${state.mobileTab === tab.id ? 'active' : ''}" data-review-tab="${tab.id}" type="button">${escapeHtml(tab.label())}</button>`).join('')}
  </div>`;
}

function mobilePane(active, content) {
  return `<section class="review-mobile-pane ${active ? 'active' : ''}">${content}</section>`;
}

function desktopShell(summary, current, detail) {
  return `
    <section class="two-col review-split">
      <div class="table-panel review-queue-panel">
        <div class="table-header">
          <div>
            <div class="table-title">${pick('工单队列', 'Case Queue')}</div>
            <div class="table-sub">${pick('每页 10 条，点击一行查看详情。', '10 per page. Click a row to inspect.')}</div>
          </div>
        </div>
        <div class="table-body">
          ${renderQueueFilters()}
          ${renderQueuePager()}
          <div class="review-table-window">${renderQueueTable()}</div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${pick('当前选择', 'Current Case')}</div>
            <div class="card-sub">${current ? escapeHtml(current.event_no || current.alert_id) : '--'}</div>
          </div>
        </div>
        <div class="card-body">${renderSelectionSummary(current)}</div>
      </div>
    </section>
    <section style="margin-top:14px">${renderDossier(detail)}</section>
    <section style="margin-top:14px">${renderActionHistory(detail)}</section>
  `;
}

function mobileShell(summary, current, detail) {
  return `
    ${reviewTabs()}
    ${mobilePane(state.mobileTab === 'queue', `<div class="table-panel review-queue-panel">
      <div class="table-header">
        <div>
          <div class="table-title">${pick('工单队列', 'Case Queue')}</div>
          <div class="table-sub">${pick('移动端默认先看队列，选中后再切详情。', 'Start with the queue, then move into detail.')}</div>
        </div>
      </div>
      <div class="table-body">
        ${renderQueueFilters()}
        ${renderQueuePager()}
        <div class="review-table-window">${renderQueueTable()}</div>
      </div>
    </div>`)}
    ${mobilePane(state.mobileTab === 'detail', `
      <div class="card" style="margin-bottom:12px">
        <div class="card-header">
          <div>
            <div class="card-title">${pick('当前选择', 'Current Case')}</div>
            <div class="card-sub">${current ? escapeHtml(current.event_no || current.alert_id) : '--'}</div>
          </div>
        </div>
        <div class="card-body">${renderSelectionSummary(current)}</div>
      </div>
      ${renderDossier(detail)}
    `)}
    ${mobilePane(state.mobileTab === 'history', renderActionHistory(detail))}
  `;
}

async function redraw(container) {
  const detail = state.detail || await fetchSelectedDetail();
  state.detail = detail;
  const current = selectedAlert();
  const summary = {
    pending: state.alerts.filter((item) => ['pending', 'assigned'].includes(item.status)).length,
    review: state.alerts.filter((item) => ['review_required', 'unresolved'].includes(item.identity_status)).length,
    resolved: state.alerts.filter((item) => item.identity_status === 'resolved').length,
    closed: state.alerts.filter((item) => ['remediated', 'ignored', 'false_positive', 'confirmed'].includes(item.status)).length,
  };

  container.innerHTML = `${pageHeader(
    'CASE OPERATIONS',
    pick('人工复核台', 'Review Desk'),
    pick('围绕证据、身份、通知和处置动作推进统一复核。', 'Move evidence, identity, notification, and resolution through one workflow.'),
    `<button class="btn btn-ghost" id="refresh-review">${pick('刷新', 'Refresh')}</button>`,
  )}
    <section class="metric-grid">
      ${metricCard(pick('待办工单', 'Actionable'), fmt(summary.pending), pick('当前页仍需处理的案件', 'Cases needing action'), 'warning')}
      ${metricCard(pick('待身份复核', 'Identity Review'), fmt(summary.review), pick('需要确认人员身份', 'Identity needs review'), 'warning')}
      ${metricCard(pick('已识别人员', 'Resolved'), fmt(summary.resolved), pick('身份已确认或修正', 'Identity already resolved'))}
      ${metricCard(pick('已闭环', 'Closed'), fmt(summary.closed), pick('已整改、已忽略或误报', 'Remediated, ignored, or false positive'))}
      ${metricCard(pick('当前页总量', 'Current Page'), fmt(state.alerts.length), pick('当前队列可见工单数', 'Visible cases in the queue'))}
    </section>
    ${isMobileView() ? mobileShell(summary, current, detail) : desktopShell(summary, current, detail)}`;

  container.querySelectorAll('[data-alert-id]').forEach((row) => {
    row.addEventListener('click', async () => {
      state.selected = row.getAttribute('data-alert-id');
      state.detail = null;
      state.actionActor = '';
      state.actionPage = 0;
      if (isMobileView()) state.mobileTab = 'detail';
      await redraw(container);
    });
  });

  bindQueueFilters(container);
  bindActionHistory(container);
  bindMobileTabs(container);

  container.querySelector('#refresh-review')?.addEventListener('click', () => render(container));
  container.querySelector('#review-prev-page')?.addEventListener('click', () => {
    state.offset = Math.max(0, state.offset - state.limit);
    render(container);
  });
  container.querySelector('#review-next-page')?.addEventListener('click', () => {
    state.offset += state.limit;
    render(container);
  });

  container.querySelector('#assign-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const currentAlert = selectedAlert();
    if (!currentAlert || !requireLoginForWrite()) return;
    try {
      await api.alerts.assign(currentAlert.alert_id, {
        assignee: container.querySelector('#assignee').value,
        assignee_email: container.querySelector('#assignee-email').value,
        note: container.querySelector('#assign-note').value,
      });
      toast.success(pick('工单已转派', 'Case assigned'));
      await render(container);
    } catch (error) {
      toast.error(pick('转派失败', 'Assignment failed'), error.message);
    }
  });

  container.querySelector('#status-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const currentAlert = selectedAlert();
    if (!currentAlert || !requireLoginForWrite()) return;
    const form = new FormData();
    form.append('new_status', container.querySelector('#new-status').value);
    form.append('note', container.querySelector('#status-note').value);
    form.append('person_id', container.querySelector('#person-id').value);
    const file = container.querySelector('#remediation-file').files[0];
    if (file) form.append('remediation_snapshot', file);
    try {
      await api.alerts.status(currentAlert.alert_id, form);
      toast.success(pick('工单已更新', 'Case updated'));
      await render(container);
    } catch (error) {
      toast.error(pick('更新失败', 'Update failed'), error.message);
    }
  });

  markPageReady(container, 'review');
}

export async function render(container) {
  container.innerHTML = `${pageHeader(
    'CASE OPERATIONS',
    pick('人工复核台', 'Review Desk'),
    pick('正在加载工单队列。', 'Loading case queue.'),
  )}${emptyState(pick('正在加载', 'Loading'))}`;
  try {
    state.limit = 10;
    const filter = activeStatusFilter();
    const alerts = await api.alerts.list({
      days: 30,
      limit: state.limit,
      offset: state.offset,
      status: filter.statuses,
      identity_status: state.identityFilter,
      mode: 'compact',
      include_media: false,
    });
    let people = { items: [] };
    if (isAuthenticated()) {
      try {
        people = await api.people.list();
      } catch {
        people = { items: [] };
      }
    }
    state.alerts = alerts.items || [];
    state.total = alerts.total || state.alerts.length;
    state.people = people.items || [];
    state.selected = state.alerts.some((item) => item.alert_id === state.selected) ? state.selected : state.alerts[0]?.alert_id || null;
    state.detail = null;
    state.actionActor = '';
    state.actionPage = 0;
    if (!selectedAlert()) state.mobileTab = 'queue';
    await redraw(container);
  } catch (error) {
    container.innerHTML = `${pageHeader(
      'CASE OPERATIONS',
      pick('人工复核台', 'Review Desk'),
      pick('围绕证据、身份、通知和处置动作推进统一复核。', 'Move evidence, identity, notification, and resolution through one workflow.'),
    )}${emptyState(pick('复核接口暂不可用', 'Review API unavailable'), error.message)}`;
    markPageReady(container, 'review');
  }
}
