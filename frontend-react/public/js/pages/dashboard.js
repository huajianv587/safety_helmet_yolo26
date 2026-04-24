import { api, getAuthUser } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import { createRealtimeChannel } from '../realtime.js?v=1';
import {
  badge,
  emptyState,
  escapeHtml,
  fmt,
  fmtPct,
  fmtTime,
  markPageReady,
  mediaImage,
  metricCard,
  pageHeader,
  renderChart,
  statusLabel,
  table,
} from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

let charts = [];
let visitorExpanded = false;
let realtimeChannels = [];
let reloadTimer = 0;

function chartColors() {
  const style = getComputedStyle(document.body);
  return {
    text: style.getPropertyValue('--text-secondary').trim(),
    grid: 'rgba(0,255,136,0.10)',
    green: style.getPropertyValue('--green').trim(),
  };
}

function trendOption(rows) {
  const c = chartColors();
  const hasData = rows.some((item) => Number(item.alerts) > 0);
  return {
    textStyle: { color: c.text, fontFamily: 'Consolas, monospace' },
    graphic: hasData ? [] : [{
      type: 'text',
      left: 'center',
      top: 'middle',
      style: { text: pick('当前时段无告警', 'No alerts in this period'), fill: c.text, font: '14px Consolas' },
    }],
    grid: { left: 38, right: 18, top: 26, bottom: 30 },
    xAxis: {
      type: 'category',
      data: rows.map((item) => item.hour),
      axisLine: { lineStyle: { color: c.grid } },
      axisLabel: { color: c.text },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: c.grid } },
      axisLabel: { color: c.text },
    },
    series: [{
      type: 'line',
      smooth: true,
      data: rows.map((item) => item.alerts),
      lineStyle: { color: c.green, width: 3 },
      areaStyle: { color: 'rgba(0,255,136,0.12)' },
      symbolSize: 6,
    }],
  };
}

function shell(actionHtml = '') {
  return pageHeader(
    'REAL TIME SAFETY OPS',
    pick('安全帽监测总览', 'Safety Helmet Overview'),
    pick('统一查看今日态势、待办工单、证据墙和摄像头健康。访客可浏览，配置写入需要登录。', 'Review daily posture, open cases, evidence, and camera health. Guests can browse; configuration changes require login.'),
    actionHtml,
  );
}

function topActions() {
  const user = getAuthUser();
  const actions = [
    `<button class="btn btn-ghost" id="refresh-dashboard">${pick('刷新', 'Refresh')}</button>`,
    `<a class="btn btn-ghost" href="#/cameras">${pick('摄像头现场', 'Live Cameras')}</a>`,
  ];
  if ((user.routes || []).includes('/operations')) {
    actions.push(`<a class="btn btn-ghost" href="#/operations">${pick('运维工作台', 'Operations Studio')}</a>`);
  }
  return actions.join('');
}

function hotspotRows(items, emptyTitle, formatter) {
  if (!items?.length) return emptyState(emptyTitle);
  return `<div class="rank-list">${items.map(formatter).join('')}</div>`;
}

function renderHotspots(hotspots = {}) {
  const mode = hotspots.mode === 'fallback_7d'
    ? pick('回退近 7 天', 'Fallback 7d')
    : pick('今日实时', 'Today');
  return `<div class="card hotspot-card">
    <div class="card-header">
      <div>
        <div class="card-title">${pick('混合热点', 'Mixed Hotspots')}</div>
        <div class="card-sub">${pick('部门、区域和摄像头同时观察，避免右侧面板空白。', 'Track departments, zones, and cameras together so this panel always says something useful.')}</div>
      </div>
      <div>${badge(hotspots.mode === 'fallback_7d' ? 'warn' : 'ready', mode)}</div>
    </div>
    <div class="card-body hotspot-grid">
      <div>
        <div class="hotspot-group-title">${pick('部门热点', 'Departments')}</div>
        ${hotspotRows(
          hotspots.departments || [],
          pick('暂无部门热点', 'No department hotspots'),
          (item) => `<div class="rank-row"><div class="rank-name">${escapeHtml(item.department || '--')}</div><div class="rank-value">${escapeHtml(fmt(item.alerts))}</div></div>`,
        )}
      </div>
      <div>
        <div class="hotspot-group-title">${pick('区域热点', 'Zones')}</div>
        ${hotspotRows(
          hotspots.zones || [],
          pick('暂无区域热点', 'No zone hotspots'),
          (item) => `<div class="rank-row"><div class="rank-name">${escapeHtml(item.zone_name || '--')}</div><div class="rank-value">${escapeHtml(fmt(item.alerts))}</div></div>`,
        )}
      </div>
      <div>
        <div class="hotspot-group-title">${pick('摄像头热点', 'Cameras')}</div>
        ${hotspotRows(
          hotspots.cameras || [],
          pick('暂无摄像头热点', 'No camera hotspots'),
          (item) => `<div class="rank-row"><div class="rank-name">${escapeHtml(item.camera_name || item.camera_id || '--')}</div><div class="rank-value">${escapeHtml(fmt(item.alerts))}</div></div>`,
        )}
      </div>
    </div>
  </div>`;
}

function renderRecentAlerts(rows) {
  return table(
    [
      pick('事件', 'Event'),
      pick('时间', 'Time'),
      pick('摄像头', 'Camera'),
      pick('人员', 'Person'),
      pick('部门', 'Department'),
      pick('状态', 'Status'),
      pick('身份', 'Identity'),
    ],
    rows,
    (item) => `<tr>
      <td>${escapeHtml(item.event_no || item.alert_id || '--')}</td>
      <td>${escapeHtml(fmtTime(item.created_at))}</td>
      <td>${escapeHtml(item.camera_name || item.camera_id || '--')}</td>
      <td>${escapeHtml(item.person_name || 'Unknown')}</td>
      <td>${escapeHtml(item.department || '--')}</td>
      <td>${badge(item.status)}</td>
      <td>${badge(item.identity_status)}</td>
    </tr>`,
  );
}

function renderCameraHealth(rows) {
  return table(
    [
      pick('摄像头', 'Camera'),
      pick('位置', 'Location'),
      pick('部门', 'Department'),
      pick('状态', 'Status'),
      'FPS',
      pick('最近心跳', 'Last Seen'),
    ],
    (rows || []).slice(0, 8),
    (item) => `<tr>
      <td>${escapeHtml(item.camera_name || item.camera_id || '--')}</td>
      <td>${escapeHtml([item.site_name, item.building_name, item.zone_name].filter(Boolean).join(' / ') || item.location || '--')}</td>
      <td>${escapeHtml(item.department || '--')}</td>
      <td>${badge(item.last_status || item.status)}</td>
      <td>${escapeHtml(fmt(item.last_fps))}</td>
      <td>${escapeHtml(fmtTime(item.last_seen_at))}</td>
    </tr>`,
  );
}

function renderVisitorRecords(rows) {
  if (!rows?.length) return emptyState(pick('暂无访客留档', 'No visitor records yet'));
  return `<div class="visitor-record-list visitor-record-list--compact">${rows.map((item) => `<article class="visitor-record visitor-record--compact">
    <div class="visitor-record__body">
      <div class="visitor-record__title">${escapeHtml(item.visitor_name || 'Guest Visitor')}</div>
      <div class="visitor-record__sub">${escapeHtml([item.visitor_company, item.visit_reason].filter(Boolean).join(' / ') || pick('现场访客记录', 'Visitor record'))}</div>
      <div class="visitor-record__meta">${escapeHtml(item.camera_name || item.camera_id || pick('未绑定摄像头', 'No camera bound'))} · ${escapeHtml(fmtTime(item.created_at))}</div>
    </div>
  </article>`).join('')}</div>`;
}

function renderVisitorDesk(data = {}) {
  const summary = data.visitor_evidence_summary || {};
  const items = summary.items || [];
  const visibleItems = visitorExpanded ? items : items.slice(0, 2);
  const cameraOptions = ['<option value="">--</option>'].concat(
    (data.cameras || []).map((item) => `<option value="${escapeHtml(item.camera_id)}">${escapeHtml(item.camera_name || item.camera_id)}</option>`),
  ).join('');
  return `<div class="card visitor-desk-card">
    <div class="card-header">
      <div>
        <div class="card-title">${pick('访客留档', 'Visitor Evidence Desk')}</div>
        <div class="card-sub">${pick('访客也能提交截图和备注，但不会进入正式告警闭环。', 'Guests can submit snapshots and notes here without creating a formal alert.')}</div>
      </div>
      <div>${badge('ready', `${pick('最近', 'Recent')} ${fmt(summary.total || 0)}`)}</div>
    </div>
    <div class="card-body visitor-desk-body visitor-desk-body--compact">
      <form id="visitor-evidence-form" class="form-grid visitor-desk-form-compact">
        <label class="form-row"><span class="form-label">${pick('访客姓名', 'Visitor Name')}</span><input class="form-input" name="visitor_name" required></label>
        <label class="form-row"><span class="form-label">${pick('访客单位', 'Visitor Company')}</span><input class="form-input" name="visitor_company"></label>
        <label class="form-row"><span class="form-label">${pick('来访事由', 'Visit Reason')}</span><input class="form-input" name="visit_reason"></label>
        <label class="form-row"><span class="form-label">${pick('关联摄像头', 'Camera')}</span><select class="form-select" name="camera_id">${cameraOptions}</select></label>
        <label class="form-row form-row-span-two"><span class="form-label">${pick('备注', 'Note')}</span><textarea class="form-textarea visitor-note-compact" name="note" placeholder="${escapeHtml(pick('例如：访客进入车间前已完成安全帽交底。', 'For example: visitor received helmet briefing before entering the workshop.'))}"></textarea></label>
        <label class="form-row form-row-span-two"><span class="form-label">${pick('截图上传', 'Snapshot')}</span><input class="form-input" name="snapshot" type="file" accept="image/png,image/jpeg" required></label>
        <div class="form-row-span-two visitor-desk-actions">
          <button class="btn btn-primary" id="submit-visitor-evidence" type="submit">${pick('提交留档', 'Submit Record')}</button>
        </div>
      </form>
      <div class="visitor-desk-divider visitor-desk-divider--compact"></div>
      <div class="visitor-record-strip">
        <div class="table-title">${pick('最近访客记录', 'Recent Visitor Records')}</div>
        <div class="table-inline-note">${pick('和正式告警证据分开显示，避免语义混淆。', 'Displayed separately from formal alert evidence so the workflow stays clear.')}</div>
        ${renderVisitorRecords(visibleItems)}
        ${items.length > 2 ? `<div class="visitor-strip-actions"><button class="btn btn-ghost btn-sm" id="toggle-visitor-records" type="button">${visitorExpanded ? pick('收起', 'Collapse') : pick('查看更多', 'Show more')}</button></div>` : ''}
      </div>
    </div>
  </div>`;
}

function renderEvidencePanel(data = {}) {
  const available = (data.evidence_alerts_available || []).slice(0, 6);
  const unavailable = (data.evidence_alerts_unavailable || []).slice(0, 4);
  const visitorItems = (data.visitor_evidence_summary?.items || []).slice(0, 2);
  return `<div class="card">
    <div class="card-header">
      <div>
        <div class="card-title">${pick('证据墙', 'Evidence Wall')}</div>
        <div class="card-sub">${pick('首屏优先显示可回看的真实证据；缺失证据收纳到次级列表。', 'Prioritize accessible evidence first. Missing or remote media stays in a quieter secondary list.')}</div>
      </div>
    </div>
    <div class="card-body">
      ${available.length ? `<div class="evidence-grid">${available.map((item) => `<div class="evidence-item">
        ${mediaImage(item.snapshot_display_url, pick('告警截图', 'Alert snapshot'), { state: item.snapshot_media_state })}
        <div class="evidence-caption">${escapeHtml(item.camera_name || item.camera_id || '--')}<br>${escapeHtml(item.event_no || item.alert_id || '--')}</div>
      </div>`).join('')}</div>` : emptyState(pick('当前没有可回看的告警证据', 'No accessible alert evidence right now'))}
      ${unavailable.length ? `<div class="evidence-secondary">
        <div class="hotspot-group-title">${pick('缺失或远程证据', 'Deferred Evidence')}</div>
        <div class="evidence-secondary-list">${unavailable.map((item) => `<div class="evidence-secondary-item">
          <span>${escapeHtml(item.event_no || item.alert_id || '--')}</span>
          <span>${escapeHtml(item.camera_name || item.camera_id || '--')}</span>
          <span>${escapeHtml(statusLabel(item.snapshot_media_state || 'missing'))}</span>
        </div>`).join('')}</div>
      </div>` : ''}
      ${visitorItems.length ? `<div class="evidence-secondary">
        <div class="hotspot-group-title">${pick('访客留档条带', 'Visitor Record Strip')}</div>
        <div class="visitor-strip visitor-strip--compact">${visitorItems.map((item) => `<div class="visitor-strip-item">
          ${mediaImage(item.snapshot_display_url, pick('访客截图', 'Visitor snapshot'), { state: item.snapshot_media_state, caption: pick('访客留档截图', 'Visitor desk snapshot') })}
          <div class="visitor-strip-copy">${escapeHtml(item.visitor_name || 'Guest Visitor')} · ${escapeHtml(fmtTime(item.created_at))}</div>
        </div>`).join('')}</div>
      </div>` : ''}
    </div>
  </div>`;
}

async function bindVisitorDesk(container, load) {
  container.querySelector('#visitor-evidence-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    if (!formData.get('snapshot') || !formData.get('snapshot').name) {
      toast.warning(pick('请先上传截图', 'Upload a snapshot first'));
      return;
    }
    try {
      await api.visitorEvidence.create(formData);
      toast.success(pick('访客留档已提交', 'Visitor record submitted'));
      visitorExpanded = false;
      form.reset();
      await load();
    } catch (error) {
      toast.error(pick('访客留档失败', 'Visitor record failed'), error.message);
    }
  });

  container.querySelector('#toggle-visitor-records')?.addEventListener('click', async () => {
    visitorExpanded = !visitorExpanded;
    await load();
  });
}

export async function render(container) {
  container.innerHTML = `${shell(topActions())}${emptyState(pick('正在加载总览数据', 'Loading overview data'))}`;

  function scheduleReload() {
    if (reloadTimer) window.clearTimeout(reloadTimer);
    reloadTimer = window.setTimeout(() => load(), 180);
  }

  async function load() {
    try {
      const data = await api.platform.overview(7);
      const metrics = data.metrics || {};
      const cameras = data.camera_summary || {};
      container.innerHTML = `${shell(topActions())}
        <section class="metric-grid">
          ${metricCard(pick('今日告警', 'Today Alerts'), fmt(metrics.today_alerts), pick('当前自然日写入的告警事件', 'Alert events written today'))}
          ${metricCard(pick('待办队列', 'Pending Queue'), fmt(metrics.pending_queue), pick('仍需推进闭环的现场工单', 'Cases still requiring action'), 'warning')}
          ${metricCard(pick('待复核', 'Review Required'), fmt(metrics.review_required), pick('身份或证据需要人工确认', 'Identity or evidence needs review'), 'warning')}
          ${metricCard(pick('启用摄像头', 'Enabled Cameras'), fmt(cameras.enabled), pick('运行配置中启用的设备', 'Enabled devices in runtime config'))}
          ${metricCard(pick('闭环率', 'Closure Rate'), fmtPct(metrics.closure_rate), pick('当前时间窗内已闭环占比', 'Closed share in the active window'))}
        </section>
        <section class="two-col">
          <div class="visual-panel">
            <div class="visual-header">
              <div>
                <div class="visual-title">${pick('今日告警趋势', 'Today Alert Trend')}</div>
                <div class="visual-sub">${pick('按小时观察告警密度', 'Hourly alert density')}</div>
              </div>
            </div>
            <div class="visual-body"><div class="chart" id="hour-chart"></div></div>
          </div>
          ${renderHotspots(data.hotspots || {})}
        </section>
        <section class="two-col" style="margin-top:14px">
          <div class="table-panel">
            <div class="table-header">
              <div>
                <div class="table-title">${pick('最近告警', 'Recent Alerts')}</div>
                <div class="table-sub">${pick('优先处理最新现场事件', 'Handle the freshest field events first')}</div>
              </div>
            </div>
            <div class="table-body">${renderRecentAlerts(data.recent_alerts || [])}</div>
          </div>
          ${renderVisitorDesk(data)}
        </section>
        <section class="two-col" style="margin-top:14px">
          ${renderEvidencePanel(data)}
          <div class="table-panel">
            <div class="table-header">
              <div>
                <div class="table-title">${pick('摄像头健康', 'Camera Health')}</div>
                <div class="table-sub">${pick('心跳、FPS 和异常一屏查看', 'Heartbeat, FPS, and exceptions in one panel')}</div>
              </div>
            </div>
            <div class="table-body">${renderCameraHealth(data.cameras || [])}</div>
          </div>
        </section>`;

      charts.forEach((item) => item?.destroy?.());
      charts = [
        renderChart(container.querySelector('#hour-chart'), trendOption(data.hourly_trend || [])),
      ];

      container.querySelector('#refresh-dashboard')?.addEventListener('click', load);
      await bindVisitorDesk(container, load);
      markPageReady(container, 'dashboard');
    } catch (error) {
      container.innerHTML = `${shell(`<button class="btn btn-ghost" id="refresh-dashboard">${pick('重试', 'Retry')}</button><a class="btn btn-ghost" href="#/cameras">${pick('摄像头现场', 'Live Cameras')}</a>`)}
        ${emptyState(pick('后端暂不可用', 'Backend unavailable'), error.message)}`;
      container.querySelector('#refresh-dashboard')?.addEventListener('click', load);
      markPageReady(container, 'dashboard');
    }
  }

  realtimeChannels.forEach((channel) => channel?.close?.());
  realtimeChannels = [
    createRealtimeChannel('dashboard', {
      onMessage(message) {
        if (['overview_snapshot', 'metrics_update', 'queue_update'].includes(message?.type)) scheduleReload();
      },
    }),
    createRealtimeChannel('alerts', {
      onMessage(message) {
        if (['alert_created', 'alert_updated'].includes(message?.type)) scheduleReload();
      },
    }),
    createRealtimeChannel('cameras', {
      onMessage(message) {
        if (['camera_status', 'frame_state'].includes(message?.type)) scheduleReload();
      },
    }),
  ];
  await load();
}

export function destroy() {
  charts.forEach((item) => item?.destroy?.());
  charts = [];
  realtimeChannels.forEach((channel) => channel?.close?.());
  realtimeChannels = [];
  if (reloadTimer) window.clearTimeout(reloadTimer);
  reloadTimer = 0;
}
