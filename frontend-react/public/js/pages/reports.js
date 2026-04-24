import { api } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import { badge, downloadCsv, emptyState, escapeHtml, fmt, fmtPct, markPageReady, metricCard, pageHeader, renderChart, table } from '../utils.js?v=1';

const STATUS_CHIPS = [
  { id: '', label: () => pick('全部状态', 'All Status') },
  { id: 'pending', label: () => pick('待处理', 'Pending') },
  { id: 'assigned', label: () => pick('已转派', 'Assigned') },
  { id: 'remediated,confirmed', label: () => pick('已整改', 'Remediated') },
  { id: 'false_positive,ignored', label: () => pick('误报 / 忽略', 'False / Ignored') },
];

let charts = [];
let state = {
  summary: null,
  rows: [],
  status: '',
  cameraId: '',
  offset: 0,
  limit: 20,
};

function colors() {
  const style = getComputedStyle(document.body);
  return {
    text: style.getPropertyValue('--text-secondary').trim(),
    grid: 'rgba(0,255,136,0.10)',
    green: style.getPropertyValue('--green').trim(),
    amber: style.getPropertyValue('--amber').trim(),
    red: style.getPropertyValue('--red').trim(),
    cyan: style.getPropertyValue('--cyan').trim(),
  };
}

function dailyOption(rows) {
  const c = colors();
  return {
    textStyle: { color: c.text, fontFamily: 'Consolas, monospace' },
    grid: { left: 42, right: 18, top: 24, bottom: 34 },
    xAxis: { type: 'category', data: rows.map((item) => item.date), axisLabel: { color: c.text }, axisLine: { lineStyle: { color: c.grid } } },
    yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: c.grid } }, axisLabel: { color: c.text } },
    series: [{ type: 'bar', data: rows.map((item) => item.alerts), itemStyle: { color: c.green, borderRadius: 4 }, barWidth: 14 }],
  };
}

function statusOption(rows) {
  const c = colors();
  return {
    textStyle: { color: c.text, fontFamily: 'Consolas, monospace' },
    legend: { bottom: 0, left: 'center', textStyle: { color: c.text }, itemWidth: 10, itemHeight: 10 },
    series: [{
      type: 'pie',
      radius: ['42%', '66%'],
      center: ['50%', '42%'],
      label: { show: false },
      labelLine: { show: false },
      data: rows.map((item) => ({ name: item.status, value: item.count })),
      color: [c.green, c.amber, c.red, c.cyan],
    }],
  };
}

function shell(actionHtml = '') {
  return pageHeader(
    'DATA PRODUCTS',
    pick('统计报表', 'Governance Reports'),
    pick('把趋势、状态、部门、摄像头和身份来源沉淀为可读的治理输出。', 'Turn trends, status, cameras, and identity sources into readable governance output.'),
    actionHtml,
  );
}

function cameraChips(summary) {
  const ranking = summary?.camera_ranking || [];
  const top = ranking.slice(0, 6);
  const activeChip = state.cameraId && !top.some((item) => item.camera_id === state.cameraId)
    ? (summary?.camera_ranking || []).find((item) => item.camera_id === state.cameraId)
    : null;
  const items = activeChip ? [activeChip, ...top] : top;
  return [
    `<button class="status-filter ${state.cameraId ? '' : 'active'}" data-report-camera="" type="button">${escapeHtml(pick('全部摄像头', 'All Cameras'))}</button>`,
    ...items.map((item) => `<button class="status-filter ${item.camera_id === state.cameraId ? 'active' : ''}" data-report-camera="${escapeHtml(item.camera_id)}" type="button">${escapeHtml(item.camera_name || item.camera_id || '--')}</button>`),
  ].join('');
}

function renderFilterBar(summary) {
  return `<div class="report-filter-stack">
    <div>
      <div class="hotspot-group-title">${pick('状态筛选', 'Status Filter')}</div>
      <div class="status-filter-row">
        ${STATUS_CHIPS.map((item) => `<button class="status-filter ${item.id === state.status ? 'active' : ''}" data-report-status="${item.id}" type="button">${escapeHtml(item.label())}</button>`).join('')}
      </div>
    </div>
    <div>
      <div class="hotspot-group-title">${pick('摄像头筛选', 'Camera Filter')}</div>
      <div class="status-filter-row">
        ${cameraChips(summary)}
      </div>
    </div>
  </div>`;
}

function rankingTable(headers, rows, rowRenderer, emptyTitle) {
  if (!rows?.length) return emptyState(emptyTitle);
  return table(headers, rows, rowRenderer);
}

function renderRowsTable() {
  return `${table(
    [pick('事件', 'Event'), pick('摄像头', 'Camera'), pick('人员', 'Person'), pick('部门', 'Department'), pick('状态', 'Status')],
    state.rows,
    (item) => `<tr>
      <td>${escapeHtml(item.event_no || item.alert_id || '--')}</td>
      <td>${escapeHtml(item.camera_name || '--')}</td>
      <td>${escapeHtml(item.person_name || '--')}</td>
      <td>${escapeHtml(item.department || '--')}</td>
      <td>${badge(item.status)}</td>
    </tr>`,
  )}
  <div class="review-pager">
    <button class="btn btn-ghost btn-sm" id="report-prev-page" ${state.offset <= 0 ? 'disabled' : ''}>${pick('上一页', 'Prev')}</button>
    <span>${escapeHtml(`${state.offset + 1}-${Math.min(state.offset + state.rows.length, state.summary?.rows_total || state.rows.length)} / ${state.summary?.rows_total || state.rows.length}`)}</span>
    <button class="btn btn-ghost btn-sm" id="report-next-page" ${(state.offset + state.limit) >= (state.summary?.rows_total || 0) ? 'disabled' : ''}>${pick('下一页', 'Next')}</button>
  </div>`;
}

async function loadData() {
  const params = {
    days: 30,
    status: state.status,
    camera_id: state.cameraId,
    preview_limit: state.limit,
    include_rows: false,
  };
  const rowParams = {
    days: 30,
    status: state.status,
    camera_id: state.cameraId,
    limit: state.limit,
    offset: state.offset,
  };
  const [summary, rows] = await Promise.all([
    api.reports.summary(params),
    api.reports.rows(rowParams),
  ]);
  state.summary = summary;
  state.rows = rows.items || [];
}

async function redraw(container) {
  const data = state.summary || {};
  const metrics = data.metrics || {};
  container.innerHTML = `${shell(`<button class="btn btn-primary" id="export-report-btn">${pick('导出 CSV', 'Export CSV')}</button>`)}
    ${renderFilterBar(data)}
    <section class="metric-grid">
      ${metricCard(pick('告警总量', 'Alert Volume'), fmt(metrics.alert_volume), pick('当前窗口内告警总量', 'Total alerts in the window'))}
      ${metricCard(pick('涉及人数', 'People Impacted'), fmt(metrics.people_impacted), pick('去重后的人数', 'Distinct people represented'))}
      ${metricCard(pick('闭环率', 'Closure Rate'), fmtPct(metrics.closure_rate), pick('已处理事件占比', 'Closed alert share'))}
      ${metricCard(pick('待办工单', 'Open Cases'), fmt(metrics.open_cases), pick('仍需推进的工单', 'Cases still open'), 'warning')}
      ${metricCard(pick('误报率', 'False Positive Rate'), fmtPct(metrics.false_positive_rate), pick('误报事件占比', 'False-positive share'), Number(metrics.false_positive_rate) ? 'danger' : '')}
    </section>
    <section class="two-col">
      <div class="visual-panel"><div class="visual-header"><div><div class="visual-title">${pick('每日趋势', 'Daily Trend')}</div></div></div><div class="visual-body"><div class="chart" id="daily-chart"></div></div></div>
      <div class="visual-panel"><div class="visual-header"><div><div class="visual-title">${pick('状态分布', 'Status Mix')}</div></div></div><div class="visual-body"><div class="chart" id="status-chart"></div></div></div>
    </section>
    <section class="two-col" style="margin-top:14px">
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('部门排行', 'Department Ranking')}</div></div></div>
        <div class="table-body">${rankingTable(
          [pick('部门', 'Department'), pick('告警', 'Alerts')],
          data.department_ranking || [],
          (item) => `<tr><td>${escapeHtml(item.department || '--')}</td><td>${escapeHtml(fmt(item.alerts))}</td></tr>`,
          pick('暂无部门排行', 'No department ranking'),
        )}</div>
      </div>
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('人员热点', 'People Hotspots')}</div></div></div>
        <div class="table-body">${rankingTable(
          [pick('人员', 'Person'), pick('工号', 'Employee'), pick('告警', 'Alerts')],
          data.people_ranking || [],
          (item) => `<tr><td>${escapeHtml(item.person_name || '--')}</td><td>${escapeHtml(item.employee_id || '--')}</td><td>${escapeHtml(fmt(item.alerts))}</td></tr>`,
          pick('暂无人员热点', 'No people hotspots'),
        )}</div>
      </div>
    </section>
    <section class="two-col" style="margin-top:14px">
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('身份来源分布', 'Identity Source Mix')}</div></div></div>
        <div class="table-body">${rankingTable(
          [pick('来源', 'Source'), pick('数量', 'Count')],
          data.identity_source_mix || [],
          (item) => `<tr><td>${escapeHtml(item.identity_source || '--')}</td><td>${escapeHtml(fmt(item.count))}</td></tr>`,
          pick('暂无身份来源统计', 'No identity source mix'),
        )}</div>
      </div>
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('摄像头排行', 'Camera Ranking')}</div></div></div>
        <div class="table-body">${rankingTable(
          [pick('摄像头', 'Camera'), pick('编号', 'Camera ID'), pick('告警', 'Alerts')],
          data.camera_ranking || [],
          (item) => `<tr><td>${escapeHtml(item.camera_name || '--')}</td><td>${escapeHtml(item.camera_id || '--')}</td><td>${escapeHtml(fmt(item.alerts))}</td></tr>`,
          pick('暂无摄像头排行', 'No camera ranking'),
        )}</div>
      </div>
    </section>
    <section class="table-panel" style="margin-top:14px">
      <div class="table-header">
        <div>
          <div class="table-title">${pick('导出预览', 'Export Preview')}</div>
          <div class="table-sub">${pick('筛选结果会同步影响表格、图表和导出文件。', 'Filters affect the table, charts, and CSV export together.')}</div>
        </div>
      </div>
      <div class="table-body">${renderRowsTable()}</div>
    </section>`;

  charts.forEach((item) => item?.destroy?.());
  charts = [
    renderChart(container.querySelector('#daily-chart'), dailyOption(data.daily_trend || [])),
    renderChart(container.querySelector('#status-chart'), statusOption(data.status_mix || [])),
  ];

  container.querySelectorAll('[data-report-status]').forEach((button) => {
    button.addEventListener('click', async () => {
      state.status = button.getAttribute('data-report-status') || '';
      state.offset = 0;
      container.innerHTML = `${shell()}${emptyState(pick('正在刷新筛选结果', 'Refreshing filters'))}`;
      await render(container);
    });
  });
  container.querySelectorAll('[data-report-camera]').forEach((button) => {
    button.addEventListener('click', async () => {
      state.cameraId = button.getAttribute('data-report-camera') || '';
      state.offset = 0;
      container.innerHTML = `${shell()}${emptyState(pick('正在刷新筛选结果', 'Refreshing filters'))}`;
      await render(container);
    });
  });
  container.querySelector('#report-prev-page')?.addEventListener('click', async () => {
    state.offset = Math.max(0, state.offset - state.limit);
    await render(container);
  });
  container.querySelector('#report-next-page')?.addEventListener('click', async () => {
    state.offset += state.limit;
    await render(container);
  });
  container.querySelector('#export-report-btn')?.addEventListener('click', async () => {
    const response = await api.reports.rows({
      days: 30,
      status: state.status,
      camera_id: state.cameraId,
      limit: 1000,
      offset: 0,
    });
    downloadCsv('safety_alert_report.csv', response.items || state.rows);
  });
  markPageReady(container, 'reports');
}

export async function render(container) {
  container.innerHTML = `${shell()}${emptyState(pick('正在加载报表', 'Loading reports'))}`;
  try {
    await loadData();
    await redraw(container);
  } catch (error) {
    container.innerHTML = `${shell(`<button class="btn btn-ghost" id="retry-reports">${pick('重试', 'Retry')}</button>`)}${emptyState(pick('报表接口暂不可用', 'Reports API unavailable'), error.message)}`;
    container.querySelector('#retry-reports')?.addEventListener('click', () => render(container));
    markPageReady(container, 'reports');
  }
}

export function destroy() {
  charts.forEach((item) => item?.destroy?.());
  charts = [];
}
