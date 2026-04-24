import { api, getAuthUser, isAuthenticated } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import { badge, emptyState, escapeHtml, fmt, fmtTime, markPageReady, metricCard, pageHeader, table, writeGuardMessage } from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

let summary = null;
let cameras = [];
let people = [];
let selectedCameraId = '';
let animationId = null;

const PIPELINE = [
  { id: 'source', label: 'Camera Source' },
  { id: 'detect', label: 'YOLO Detection' },
  { id: 'identity', label: 'Identity Match' },
  { id: 'evidence', label: 'Evidence Store' },
  { id: 'review', label: 'Review Workflow' },
  { id: 'notify', label: 'Notification' },
];

function selectedCamera() {
  return cameras.find((item) => item.camera_id === selectedCameraId) || cameras[0] || {};
}

function shell(actionHtml = '') {
  return pageHeader(
    'FIELD CONFIG CENTER',
    pick('现场配置中心', 'Field Config Center'),
    pick('左侧维护摄像头配置，右侧集中查看运行摘要、路径状态和快捷入口。', 'Maintain camera runtime config on the left and keep runtime summary, path state, and quick links on the right.'),
    actionHtml,
  );
}

function fillForm(container, item = {}) {
  container.querySelector('#cfg-camera-id').value = item.camera_id || '';
  container.querySelector('#cfg-camera-name').value = item.camera_name || '';
  container.querySelector('#cfg-source').value = item.source || '0';
  container.querySelector('#cfg-enabled').checked = item.enabled !== false;
  container.querySelector('#cfg-site').value = item.site_name || 'Default Site';
  container.querySelector('#cfg-building').value = item.building_name || 'Main Building';
  container.querySelector('#cfg-floor').value = item.floor_name || 'Floor 1';
  container.querySelector('#cfg-workshop').value = item.workshop_name || 'Workshop A';
  container.querySelector('#cfg-zone').value = item.zone_name || 'Zone A';
  container.querySelector('#cfg-department').value = item.department || '';
  container.querySelector('#cfg-owner').value = item.responsible_department || item.department || '';
  container.querySelector('#cfg-emails').value = Array.isArray(item.alert_emails) ? item.alert_emails.join(',') : '';
  container.querySelector('#cfg-person').value = item.default_person_id || '';
}

function readForm(container) {
  return {
    camera_id: container.querySelector('#cfg-camera-id').value.trim(),
    camera_name: container.querySelector('#cfg-camera-name').value.trim(),
    source: container.querySelector('#cfg-source').value.trim(),
    enabled: container.querySelector('#cfg-enabled').checked,
    location: [container.querySelector('#cfg-site').value, container.querySelector('#cfg-zone').value].filter(Boolean).join(' / '),
    department: container.querySelector('#cfg-department').value.trim(),
    site_name: container.querySelector('#cfg-site').value.trim(),
    building_name: container.querySelector('#cfg-building').value.trim(),
    floor_name: container.querySelector('#cfg-floor').value.trim(),
    workshop_name: container.querySelector('#cfg-workshop').value.trim(),
    zone_name: container.querySelector('#cfg-zone').value.trim(),
    responsible_department: container.querySelector('#cfg-owner').value.trim(),
    alert_emails: container.querySelector('#cfg-emails').value.split(',').map((item) => item.trim()).filter(Boolean),
    default_person_id: container.querySelector('#cfg-person').value.trim(),
  };
}

function runtimeKpis() {
  const cameraMetrics = summary?.cameras || {};
  const storage = summary?.storage || {};
  const auth = summary?.auth || {};
  const notifications = summary?.notifications || {};
  return `<section class="metric-grid">
    ${metricCard(pick('启用摄像头', 'Enabled Cameras'), fmt(cameraMetrics.enabled), pick('参与监控的设备数量', 'Devices active in monitoring'))}
    ${metricCard(pick('活跃上报', 'Reporting'), fmt(cameraMetrics.reporting), pick('近期有状态上报的设备', 'Devices reporting status'))}
    ${metricCard(pick('存储后端', 'Storage Backend'), fmt(storage.effective_backend || storage.requested_backend), pick('当前仓储运行模式', 'Current repository backend'))}
    ${metricCard(pick('账号状态', 'Auth State'), auth.configured ? pick('已配置', 'Configured') : pick('未配置', 'Not configured'), pick('写操作需要可信账号', 'Write actions require a trusted account'), auth.configured ? '' : 'warning')}
    ${metricCard(pick('通知链路', 'Notification'), notifications.email_enabled ? pick('邮件启用', 'Email enabled') : pick('未启用', 'Disabled'), pick('SMTP 与默认接收人摘要', 'SMTP and recipient summary'), notifications.email_enabled ? '' : 'warning')}
  </section>`;
}

function authGuard() {
  const text = writeGuardMessage();
  return text ? `<div class="guard-note">${escapeHtml(text)}</div>` : '';
}

function editorPanel() {
  const submitLabel = isAuthenticated() ? pick('保存到运行配置', 'Save Runtime Config') : pick('登录后保存', 'Login to Save');
  const peopleOptions = ['<option value="">--</option>'].concat(
    people.map((person) => `<option value="${escapeHtml(person.person_id)}">${escapeHtml([person.name, person.employee_id, person.department].filter(Boolean).join(' / '))}</option>`),
  ).join('');
  return `<div class="run-panel">
    <div class="run-panel__header">
      <div>
        <div class="run-panel__title">${pick('摄像头运行配置', 'Camera Runtime Config')}</div>
        <div class="run-panel__sub">${pick('本地设备、本地路径或环境变量占位符；禁止明文远程流地址。', 'Local device, local path, or env placeholder only. Plain remote URLs are rejected.')}</div>
      </div>
    </div>
    <div class="run-panel__body">
      ${authGuard()}
      <form id="config-camera-form" class="form-grid">
        <label class="form-row"><span class="form-label">camera_id</span><input class="form-input" id="cfg-camera-id" required></label>
        <label class="form-row"><span class="form-label">camera_name</span><input class="form-input" id="cfg-camera-name"></label>
        <label class="form-row"><span class="form-label">source</span><input class="form-input" id="cfg-source" value="0"></label>
        <label class="form-row"><span class="form-label">enabled</span><span><input id="cfg-enabled" type="checkbox" checked> ${pick('启用', 'Enabled')}</span></label>
        <label class="form-row"><span class="form-label">site_name</span><input class="form-input" id="cfg-site"></label>
        <label class="form-row"><span class="form-label">building_name</span><input class="form-input" id="cfg-building"></label>
        <label class="form-row"><span class="form-label">floor_name</span><input class="form-input" id="cfg-floor"></label>
        <label class="form-row"><span class="form-label">workshop_name</span><input class="form-input" id="cfg-workshop"></label>
        <label class="form-row"><span class="form-label">zone_name</span><input class="form-input" id="cfg-zone"></label>
        <label class="form-row"><span class="form-label">department</span><input class="form-input" id="cfg-department"></label>
        <label class="form-row"><span class="form-label">responsible_department</span><input class="form-input" id="cfg-owner"></label>
        <label class="form-row"><span class="form-label">alert_emails</span><input class="form-input" id="cfg-emails"></label>
        <label class="form-row"><span class="form-label">default_person_id</span><select class="form-select" id="cfg-person">${peopleOptions}</select></label>
      </form>
    </div>
    <div class="run-panel__foot">
      <button class="btn btn-primary" id="save-config-camera-btn">${submitLabel}</button>
      <button class="btn btn-ghost" id="try-remote-source-btn">${pick('测试非法远程源', 'Test Remote Rejection')}</button>
    </div>
  </div>`;
}

function statusPanel() {
  const storage = summary?.storage || {};
  const auth = summary?.auth || {};
  const notifications = summary?.notifications || {};
  const model = summary?.model || {};
  const paths = summary?.runtime_paths || {};
  const user = getAuthUser();
  const opsLink = (user.routes || []).includes('/operations')
    ? `<a class="btn btn-ghost" href="#/operations">${pick('打开运维工作台', 'Open Operations Studio')}</a>`
    : '';
  return `<div class="results-panel">
    <div class="results-panel__header">
      <div>
        <div class="card-title">${pick('运行状态摘要', 'Runtime Status')}</div>
        <div class="card-sub">${pick('用来填满右侧工作区，不再让信息摘要挤在左下角。', 'Move the summary into the right workspace instead of leaving it buried below the editor.')}</div>
      </div>
      <button class="btn btn-ghost btn-sm" id="refresh-config">${pick('刷新状态', 'Refresh State')}</button>
    </div>
    <div class="results-panel__body">
      <div class="detail-list">
        <div class="detail-item"><div class="detail-key">${pick('后端', 'Backend')}</div><div class="detail-value">${escapeHtml(fmt(storage.effective_backend))}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('Supabase', 'Supabase')}</div><div class="detail-value">${badge(storage.supabase_configured ? 'configured' : 'pending')}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('账号', 'Auth')}</div><div class="detail-value">${auth.configured ? `${escapeHtml(fmt(auth.enabled_users))} users` : pick('未配置', 'Not configured')}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('通知', 'Notify')}</div><div class="detail-value">${notifications.email_enabled ? pick('邮件链路启用', 'Email delivery enabled') : pick('邮件链路未启用', 'Email delivery disabled')}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('模型', 'Model')}</div><div class="detail-value">${pick('置信度', 'Confidence')} ${escapeHtml(fmt(model.confidence))} / ${escapeHtml(fmt(model.device))}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('截图目录', 'Snapshots')}</div><div class="detail-value">${paths.snapshot_dir?.exists ? pick('存在', 'Exists') : pick('缺失', 'Missing')} / ${paths.snapshot_dir?.writable ? pick('可写', 'Writable') : pick('不可写', 'Read only')}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('运行目录', 'Runtime Dir')}</div><div class="detail-value">${paths.runtime_dir?.exists ? pick('存在', 'Exists') : pick('缺失', 'Missing')} / ${paths.runtime_dir?.writable ? pick('可写', 'Writable') : pick('不可写', 'Read only')}</div></div>
        <div class="detail-item"><div class="detail-key">${pick('身份登记', 'Registry')}</div><div class="detail-value">${paths.identity_registry?.exists ? pick('存在', 'Exists') : pick('缺失', 'Missing')} / ${paths.identity_registry?.writable ? pick('可写', 'Writable') : pick('不可写', 'Read only')}</div></div>
      </div>
      <div class="config-links">
        <a class="btn btn-ghost" href="#/cameras">${pick('打开摄像头现场', 'Open Live Cameras')}</a>
        ${opsLink}
      </div>
    </div>
  </div>`;
}

function pipelineCard() {
  return `<div class="card config-pipeline-card">
    <div class="card-header">
      <div>
        <div class="card-title">${pick('闭环流水线', 'Closed-loop Pipeline')}</div>
        <div class="card-sub">${pick('从视频源到通知的安全帽监测链路。', 'Safety helmet monitoring path from stream source to notification.')}</div>
      </div>
      <div class="status-row"><span class="status-dot online"></span><span class="status-label">${pick('链路就绪', 'Pipeline ready')}</span></div>
    </div>
    <div class="card-body"><canvas id="config-pipeline-canvas" height="170"></canvas></div>
  </div>`;
}

function cameraInventory() {
  return `<div class="table-panel">
    <div class="table-header">
      <div>
        <div class="table-title">${pick('设备清单', 'Device Inventory')}</div>
        <div class="table-sub">${pick('点击设备加载到左侧配置表单。', 'Click a device to load it into the config form.')}</div>
      </div>
    </div>
    <div class="table-body">${table(
      [pick('摄像头', 'Camera'), 'source', pick('区域', 'Zone'), pick('责任部门', 'Owner'), pick('状态', 'Status'), pick('心跳', 'Heartbeat')],
      cameras,
      (item) => `<tr data-config-camera-id="${escapeHtml(item.camera_id)}">
        <td>${escapeHtml(item.camera_name || item.camera_id || '--')}</td>
        <td>${escapeHtml(item.source || '--')}</td>
        <td>${escapeHtml([item.site_name, item.workshop_name, item.zone_name].filter(Boolean).join(' / ') || item.location || '--')}</td>
        <td>${escapeHtml(item.responsible_department || item.department || '--')}</td>
        <td>${badge(item.last_status || item.status)}</td>
        <td>${escapeHtml(fmtTime(item.last_seen_at))}</td>
      </tr>`,
    )}</div>
  </div>`;
}

function drawPipeline(container) {
  if (animationId) cancelAnimationFrame(animationId);
  const canvas = container.querySelector('#config-pipeline-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.parentElement?.clientWidth || 760;
  const isMobile = window.matchMedia('(max-width: 860px)').matches;
  const height = isMobile ? 440 : 170;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = '100%';
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  let tick = 0;

  function draw() {
    tick += 0.012;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = document.body.classList.contains('light') ? '#f0f5ef' : '#050807';
    ctx.fillRect(0, 0, width, height);
    const gap = isMobile ? height / (PIPELINE.length + 1) : width / (PIPELINE.length + 1);
    const y = height / 2;
    ctx.lineWidth = 2;
    for (let index = 0; index < PIPELINE.length - 1; index += 1) {
      const x1 = isMobile ? width / 2 : gap * (index + 1);
      const x2 = isMobile ? width / 2 : gap * (index + 2);
      const y1 = isMobile ? gap * (index + 1) : y;
      const y2 = isMobile ? gap * (index + 2) : y;
      ctx.strokeStyle = 'rgba(0,255,136,0.22)';
      ctx.beginPath();
      ctx.moveTo(isMobile ? x1 : x1 + 34, isMobile ? y1 + 31 : y);
      ctx.lineTo(isMobile ? x2 : x2 - 34, isMobile ? y2 - 31 : y);
      ctx.stroke();
      const phase = (tick + index * 0.18) % 1;
      const px = isMobile ? x1 : x1 + 34 + ((x2 - x1 - 68) * phase);
      const py = isMobile ? y1 + 31 + ((y2 - y1 - 62) * phase) : y;
      ctx.fillStyle = '#00ff88';
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
    }
    PIPELINE.forEach((node, index) => {
      const x = isMobile ? width / 2 : gap * (index + 1);
      const nodeY = isMobile ? gap * (index + 1) : y;
      const nodeWidth = isMobile ? Math.min(220, Math.max(160, width - 70)) : 96;
      ctx.fillStyle = 'rgba(0,255,136,0.08)';
      ctx.strokeStyle = 'rgba(0,255,136,0.42)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(x - nodeWidth / 2, nodeY - 28, nodeWidth, 56, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#00ff88';
      ctx.font = '11px Consolas, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(String(index + 1).padStart(2, '0'), x, nodeY - 4);
      ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text-secondary').trim();
      ctx.font = '10px Consolas, monospace';
      ctx.fillText(node.label, x, nodeY + 14);
    });
    animationId = requestAnimationFrame(draw);
  }

  draw();
}

async function saveCamera(container, payload) {
  if (!isAuthenticated()) {
    toast.warning(pick('请先登录', 'Login required'), pick('访客模式只能浏览配置，不能写入真实数据。', 'Guest mode can browse configuration but cannot write live data.'));
    window.location.hash = '#/login';
    return;
  }
  await api.cameras.save(payload);
  toast.success(pick('运行配置已保存', 'Runtime configuration saved'));
  await render(container);
}

async function redraw(container) {
  cameras = summary?.cameras?.items || [];
  if (!selectedCameraId) selectedCameraId = cameras[0]?.camera_id || '';
  container.innerHTML = `${shell(`<button class="btn btn-ghost" id="refresh-config-top">${pick('刷新配置', 'Refresh Config')}</button>`)}
    ${runtimeKpis()}
    <section class="config-command-grid">
      ${editorPanel()}
      <div class="config-right-stack">
        ${statusPanel()}
        ${pipelineCard()}
      </div>
    </section>
    <section style="margin-top:14px">
      ${cameraInventory()}
    </section>`;
  fillForm(container, selectedCamera());
  drawPipeline(container);
  container.querySelector('#refresh-config-top')?.addEventListener('click', () => render(container));
  container.querySelector('#refresh-config')?.addEventListener('click', () => render(container));
  container.querySelectorAll('[data-config-camera-id]').forEach((row) => {
    row.addEventListener('click', () => {
      selectedCameraId = row.getAttribute('data-config-camera-id') || '';
      fillForm(container, selectedCamera());
    });
  });
  container.querySelector('#save-config-camera-btn')?.addEventListener('click', async () => {
    try {
      await saveCamera(container, readForm(container));
    } catch (error) {
      toast.error(pick('保存失败', 'Save failed'), error.message);
    }
  });
  container.querySelector('#try-remote-source-btn')?.addEventListener('click', async () => {
    const payload = { ...readForm(container), source: 'rtsp://camera.example/live' };
    if (!payload.camera_id) payload.camera_id = 'remote-rejection-test';
    try {
      await saveCamera(container, payload);
      toast.warning(pick('非法远程源未被拒绝', 'Remote source was not rejected'));
    } catch (error) {
      toast.success(pick('非法远程源已被拒绝', 'Remote source rejected'), error.message);
    }
  });
  markPageReady(container, 'config');
}

export async function render(container) {
  container.innerHTML = `${shell()}${emptyState(pick('正在加载配置摘要', 'Loading configuration summary'))}`;
  try {
    const [summaryPayload, peoplePayload] = await Promise.all([
      api.config.summary(),
      isAuthenticated() ? api.people.list().catch(() => ({ items: [] })) : Promise.resolve({ items: [] }),
    ]);
    summary = summaryPayload;
    people = peoplePayload.items || [];
    await redraw(container);
  } catch (error) {
    summary = {
      cameras: { enabled: 0, reporting: 0, items: [] },
      storage: { effective_backend: 'offline', requested_backend: 'offline' },
      auth: { configured: false, enabled_users: 0 },
      notifications: { email_enabled: false },
      model: {},
      runtime_paths: {},
      offline_error: error.message,
    };
    people = [];
    await redraw(container);
    toast.warning(pick('配置摘要不可用', 'Config summary unavailable'), error.message);
  }
}

export function destroy() {
  if (animationId) cancelAnimationFrame(animationId);
  animationId = null;
}
