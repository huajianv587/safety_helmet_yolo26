import { api, clearAuth, getAuthUser, isAuthenticated } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import { badge, emptyState, escapeHtml, fmt, fmtPct, fmtTime, markPageReady, metricCard, pageHeader, table } from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

const SECTION_ORDER = [
  ['coverage', () => pick('能力矩阵', 'Coverage Matrix')],
  ['readiness', () => pick('部署就绪', 'Readiness')],
  ['services', () => pick('服务状态', 'Services')],
  ['identity', () => pick('身份注册表', 'Identity')],
  ['evidence-delivery', () => pick('证据与交付', 'Evidence & Delivery')],
  ['model-feedback', () => pick('模型反馈', 'Model Feedback')],
  ['quality-lab', () => pick('质量实验室', 'Quality Lab')],
  ['backup-release', () => pick('备份与发布', 'Backup & Release')],
  ['notifications', () => pick('通知中心', 'Notifications')],
  ['access-admin', () => pick('账号管理', 'Access Admin')],
  ['runtime-modes', () => pick('运行模式', 'Runtime Modes')],
];

function currentSection() {
  const query = new URLSearchParams((window.location.hash.split('?')[1] || ''));
  return query.get('section') || 'coverage';
}

function shell(action = '') {
  return pageHeader(
    'OPS CONTROL STUDIO',
    pick('运维工作台', 'Operations Studio'),
    pick('把 readiness、服务控制、身份覆盖、模型反馈、备份发布和深链入口集中到同一套终端界面。', 'Bring readiness, service control, identity coverage, model feedback, backup and release workflows into one terminal surface.'),
    action,
  );
}

function sectionTabs(active) {
  return `<div class="ops-section-tabs">${SECTION_ORDER.map(([id, label]) => `<a class="topbar-chip ${id === active ? 'active' : ''}" href="#/operations?section=${id}">${escapeHtml(label())}</a>`).join('')}</div>`;
}

function sectionBlock(id, title, body) {
  return `<section class="card ops-section" id="ops-${id}">
    <div class="card-header"><div><div class="card-title">${escapeHtml(title)}</div></div></div>
    <div class="card-body">${body}</div>
  </section>`;
}

function canAdmin() {
  return getAuthUser().role === 'admin';
}

function promptConfirmText(actionLabel) {
  const value = window.prompt(`${actionLabel}\n${pick('请输入确认词 HELMET OPS', 'Enter confirmation text HELMET OPS')}`, '');
  return value || '';
}

function renderCoverage(data) {
  return sectionBlock('coverage', pick('后端能力覆盖矩阵', 'Backend Capability Coverage'), `
    <section class="metric-grid">
      ${metricCard(pick('能力总数', 'Capabilities'), fmt(data.summary?.total), pick('已分类的后端能力', 'Backend capabilities classified'))}
      ${metricCard(pick('界面承载', 'UI Surfaces'), fmt(data.summary?.ui_surface), pick('已有前端界面承载', 'Capabilities visible in the UI'))}
      ${metricCard(pick('内部能力', 'Internal Only'), fmt(data.summary?.internal_only), pick('作为内部实现或离线脚本保留', 'Kept internal or offline'))}
      ${metricCard(pick('覆盖源文件', 'Covered Sources'), `${fmt(data.summary?.covered_sources)} / ${fmt(data.summary?.required_sources)}`, pick('计划要求的源文件覆盖', 'Required source files covered'))}
      ${metricCard(pick('覆盖告警', 'Coverage Errors'), fmt((data.coverage_errors || []).length), pick('必须归零', 'Must be zero'), (data.coverage_errors || []).length ? 'danger' : '')}
    </section>
    ${(data.coverage_errors || []).length ? `<div class="guard-note">${escapeHtml(data.coverage_errors.join(' | '))}</div>` : ''}
    ${table(
      [pick('能力', 'Capability'), pick('来源', 'Source'), pick('分类', 'Category'), pick('模式', 'Mode'), pick('承载面', 'Surface')],
      data.items || [],
      (item) => `<tr>
        <td><strong>${escapeHtml(item.title || item.capability_id || '--')}</strong><div class="table-inline-note">${escapeHtml(item.summary || '--')}</div></td>
        <td>${escapeHtml(item.source_module || '--')}</td>
        <td>${escapeHtml(item.category || '--')}</td>
        <td>${badge(item.mode)}</td>
        <td>${escapeHtml(item.surface_route || item.internal_only_reason || '--')}</td>
      </tr>`,
    )}
  `);
}

function renderReadiness(data) {
  const checks = data.checks || [];
  const missing = checks.filter((item) => item.status === 'missing').length;
  const warn = checks.filter((item) => item.status === 'warn').length;
  const ready = checks.filter((item) => item.status === 'ready').length;
  return sectionBlock('readiness', pick('部署就绪检查', 'Deployment Readiness'), `
    <section class="metric-grid">
      ${metricCard(pick('就绪', 'Ready'), fmt(ready), pick('通过检查项', 'Passing checks'))}
      ${metricCard(pick('预警', 'Warnings'), fmt(warn), pick('建议尽快补齐', 'Needs follow-up'), warn ? 'warning' : '')}
      ${metricCard(pick('缺失', 'Missing'), fmt(missing), pick('会阻塞部署或闭环', 'Blocks deployment or loop closure'), missing ? 'danger' : '')}
      ${metricCard(pick('登记人数', 'Registry People'), fmt(data.identity?.registry_people), pick('身份登记记录', 'Registered people'))}
      ${metricCard(pick('启用摄像头', 'Enabled Cameras'), fmt(data.cameras?.enabled), pick('运行配置已启用', 'Enabled in runtime config'))}
    </section>
    <div class="detail-list" style="margin-bottom:14px">
      <div class="detail-item"><div class="detail-key">${pick('配置文件', 'Runtime Config')}</div><div class="detail-value">${escapeHtml(fmt(data.config?.runtime_config))}</div></div>
      <div class="detail-item"><div class="detail-key">${pick('模型文件', 'Detector Model')}</div><div class="detail-value">${escapeHtml(fmt(data.model?.label))}</div></div>
      <div class="detail-item"><div class="detail-key">${pick('身份登记', 'Registry')}</div><div class="detail-value">${escapeHtml(fmt(data.identity?.registry_label))}</div></div>
      <div class="detail-item"><div class="detail-key">${pick('人脸样本', 'Face Profiles')}</div><div class="detail-value">${escapeHtml(fmt(data.identity?.face_profile_label))}</div></div>
    </div>
    ${(data.next_actions || []).length ? `<div class="ops-note-stack">${(data.next_actions || []).map((item) => `<div class="guard-note">${escapeHtml(item)}</div>`).join('')}</div>` : emptyState(pick('暂无额外动作建议', 'No follow-up actions'))}
    <div style="margin-top:14px">${table(
      [pick('检查项', 'Check'), pick('状态', 'Status'), pick('详情', 'Detail')],
      data.checks || [],
      (item) => `<tr><td>${escapeHtml(item.check_id || '--')}</td><td>${badge(item.status)}</td><td>${escapeHtml(item.detail || '--')}</td></tr>`,
    )}</div>
  `);
}

function renderServices(data) {
  const rows = Object.values(data.services || {});
  return sectionBlock('services', pick('服务健康与控制', 'Service Health and Control'), `
    <section class="metric-grid">
      ${metricCard(pick('服务数', 'Services'), fmt(rows.length), pick('被监控的核心服务', 'Core services tracked'))}
      ${metricCard(pick('本机预览', 'Local Preview'), fmt(data.camera_summary?.local_preview), pick('可浏览器直连的本机摄像头', 'Browser-preview cameras'))}
      ${metricCard(pick('实时帧', 'Live Frames'), fmt(data.camera_summary?.live_frames), pick('monitor 写入的最新帧', 'Frames written by monitor'))}
      ${metricCard(pick('配置设备', 'Configured Cameras'), fmt(data.camera_summary?.configured), pick('配置文件中的摄像头', 'Configured cameras'))}
      ${metricCard(pick('启用设备', 'Enabled Cameras'), fmt(data.camera_summary?.enabled), pick('已启用的监控源', 'Enabled sources'))}
    </section>
    ${table(
      [pick('服务', 'Service'), pick('状态', 'Status'), pick('详情', 'Detail'), pick('操作', 'Actions')],
      rows,
      (item) => `<tr>
        <td>${escapeHtml(item.service || '--')}</td>
        <td>${badge(item.status)}</td>
        <td>${escapeHtml(item.detail || '--')}</td>
        <td>${canAdmin() && ['monitor', 'dashboard'].includes(item.service) ? `
          <div class="inline-actions">
            <button class="btn btn-ghost btn-sm" data-service-action="${escapeHtml(item.service)}:start">${pick('启动', 'Start')}</button>
            <button class="btn btn-ghost btn-sm" data-service-action="${escapeHtml(item.service)}:restart">${pick('重启', 'Restart')}</button>
            <button class="btn btn-danger btn-sm" data-service-action="${escapeHtml(item.service)}:stop">${pick('停止', 'Stop')}</button>
          </div>` : '--'}
        </td>
      </tr>`,
    )}
    <div style="margin-top:14px">${table(
      [pick('运行模式', 'Runtime Mode'), pick('可用', 'Available'), pick('入口', 'Entry'), pick('说明', 'Description')],
      data.runtime_modes || [],
      (item) => `<tr><td>${escapeHtml(item.label || '--')}</td><td>${badge(item.available ? 'ready' : 'missing', item.available ? pick('可用', 'Available') : pick('不可用', 'Unavailable'))}</td><td>${escapeHtml(item.entry || '--')}</td><td>${escapeHtml(item.description || '--')}</td></tr>`,
    )}</div>
  `);
}

function renderIdentity(data) {
  return sectionBlock('identity', pick('身份注册表覆盖', 'Identity Registry Coverage'), `
    <section class="metric-grid">
      ${metricCard(pick('登记人数', 'Active People'), fmt(data.active_people), pick('有效登记人员', 'Active registry entries'))}
      ${metricCard(pick('别名覆盖', 'Alias Coverage'), fmt(data.people_with_aliases), pick('具备 aliases 的人数', 'People with aliases'))}
      ${metricCard(pick('工牌关键词', 'Badge Keywords'), fmt(data.people_with_badge_keywords), pick('具备 badge keywords 的人数', 'People with badge keywords'))}
      ${metricCard(pick('相机绑定', 'Camera Bindings'), fmt(data.people_with_camera_bindings), pick('具备默认相机绑定的人数', 'People with default camera bindings'))}
      ${metricCard(pick('人脸样本', 'Face Samples'), fmt(data.people_with_face_samples), pick('具备本地人脸样本的人数', 'People with face samples'))}
    </section>
    ${canAdmin() ? `<div class="inline-actions" style="margin-bottom:14px"><button class="btn btn-ghost" id="ops-identity-sync">${pick('同步登记到后端', 'Sync Registry')}</button><button class="btn btn-ghost" id="ops-identity-preview">${pick('预览默认绑定建议', 'Preview Default Bindings')}</button><button class="btn btn-primary" id="ops-identity-apply">${pick('应用默认绑定建议', 'Apply Default Bindings')}</button></div>` : ''}
    <div class="two-col">
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('未覆盖重点名单', 'Coverage Gaps')}</div></div></div><div class="table-body">${table(
        [pick('人员', 'Person'), pick('部门', 'Department'), pick('缺口', 'Missing')],
        data.incomplete_people || [],
        (item) => `<tr><td>${escapeHtml(item.name || item.person_id || '--')}</td><td>${escapeHtml(item.department || '--')}</td><td>${escapeHtml((item.missing || []).join(', ') || '--')}</td></tr>`,
      )}</div></div>
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('默认绑定建议', 'Default Camera Suggestions')}</div></div></div><div class="table-body">${table(
        [pick('摄像头', 'Camera'), pick('当前默认', 'Current'), pick('建议人选', 'Suggested'), pick('分数', 'Score')],
        data.camera_default_suggestions || [],
        (item) => `<tr><td>${escapeHtml(item.camera_name || item.camera_id || '--')}</td><td>${escapeHtml(item.current_default_person_id || '--')}</td><td>${escapeHtml(item.suggested_name || item.suggested_person_id || '--')}</td><td>${escapeHtml(fmt(item.suggested_score))}</td></tr>`,
      )}</div></div>
    </div>
  `);
}

function renderEvidenceDelivery(data) {
  return sectionBlock('evidence-delivery', pick('证据与交付', 'Evidence and Delivery'), `
    <section class="metric-grid">
      ${metricCard(pick('存储后端', 'Storage Backend'), fmt(data.storage?.requested_backend), pick('当前请求的仓储模式', 'Requested storage mode'))}
      ${metricCard(pick('上传对象存储', 'Upload Storage'), data.storage?.upload_to_supabase_storage ? pick('启用', 'Enabled') : pick('关闭', 'Disabled'), pick('是否写入对象存储', 'Object storage delivery'))}
      ${metricCard(pick('本地保留', 'Keep Local'), data.storage?.keep_local_copy ? pick('启用', 'Enabled') : pick('关闭', 'Disabled'), pick('是否保留本地副本', 'Keep local copy'))}
      ${metricCard(pick('私有桶', 'Private Bucket'), data.storage?.private_bucket ? pick('启用', 'Enabled') : pick('关闭', 'Disabled'), pick('证据通过签名 URL 访问', 'Evidence via signed URLs'))}
      ${metricCard(pick('默认接收人', 'Recipients'), fmt((data.notifications?.default_recipients || []).length), pick('通知默认接收人数', 'Default notification recipients'))}
    </section>
    ${canAdmin() ? `<div class="inline-actions" style="margin-bottom:14px"><button class="btn btn-ghost" id="ops-validate-storage">${pick('验证存储交付', 'Validate Storage')}</button><button class="btn btn-ghost" id="ops-validate-notification">${pick('验证通知交付', 'Validate Notification')}</button></div>` : ''}
    <div class="two-col">
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('最近通知记录', 'Recent Notification Logs')}</div></div></div><div class="table-body">${table(
        [pick('事件', 'Event'), pick('接收人', 'Recipient'), pick('通道', 'Channel'), pick('状态', 'Status'), pick('时间', 'Time')],
        data.notifications?.recent_logs || [],
        (item) => `<tr><td>${escapeHtml(item.event_no || item.alert_id || '--')}</td><td>${escapeHtml(item.recipient || '--')}</td><td>${escapeHtml(item.channel || '--')}</td><td>${badge(item.status)}</td><td>${escapeHtml(fmtTime(item.created_at))}</td></tr>`,
      )}</div></div>
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('验证审计', 'Validation Audit')}</div></div></div><div class="table-body">${table(
        [pick('实体', 'Entity'), pick('动作', 'Action'), pick('操作者', 'Actor'), pick('时间', 'Time')],
        data.validation_logs || [],
        (item) => `<tr><td>${escapeHtml(item.entity_type || '--')}</td><td>${escapeHtml(item.action_type || '--')}</td><td>${escapeHtml(item.actor || '--')}</td><td>${escapeHtml(fmtTime(item.created_at))}</td></tr>`,
      )}</div></div>
    </div>
  `);
}

function renderModelFeedback(data) {
  return sectionBlock('model-feedback', pick('模型反馈闭环', 'Model Feedback Loop'), `
    <section class="metric-grid">
      ${metricCard(pick('难例总量', 'Hard Cases'), fmt(data.hard_cases_total), pick('当前反馈池样本数', 'Current feedback pool size'))}
      ${metricCard(pick('导出记录', 'Exports'), fmt((data.exports || []).length), pick('已导出的反馈批次', 'Export batches'))}
      ${metricCard(pick('数据集构建', 'Datasets'), fmt((data.datasets || []).length), pick('已生成的数据集包', 'Dataset builds'))}
      ${metricCard(pick('注册模型', 'Registered Models'), fmt(data.models?.registered), pick('模型注册表中的候选模型', 'Registered candidate models'))}
      ${metricCard(pick('当前激活模型', 'Active Model'), fmt(data.models?.active_model || '--'), pick('当前生产模型标识', 'Current promoted model'))}
    </section>
    ${canAdmin() ? `<div class="inline-actions" style="margin-bottom:14px"><button class="btn btn-ghost" id="ops-export-feedback">${pick('导出反馈样本', 'Export Feedback')}</button><button class="btn btn-primary" id="ops-build-dataset">${pick('构建反馈数据集', 'Build Feedback Dataset')}</button></div>` : ''}
    <div class="two-col">
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('导出记录', 'Exports')}</div></div></div><div class="table-body">${table(
        [pick('导出批次', 'Export'), pick('案例数', 'Cases'), pick('时间', 'Time')],
        data.exports || [],
        (item) => `<tr><td>${escapeHtml(item.export_id || '--')}</td><td>${escapeHtml(fmt(item.case_count))}</td><td>${escapeHtml(fmtTime(item.created_at))}</td></tr>`,
      )}</div></div>
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('数据集记录', 'Datasets')}</div></div></div><div class="table-body">${table(
        [pick('数据集', 'Dataset'), pick('配置', 'Manifest'), pick('时间', 'Time')],
        data.datasets || [],
        (item) => `<tr><td>${escapeHtml(item.dataset_id || '--')}</td><td>${escapeHtml(item.manifest_path || '--')}</td><td>${escapeHtml(fmtTime(item.created_at))}</td></tr>`,
      )}</div></div>
    </div>
  `);
}

function qualityStateBadge(state) {
  const labels = {
    ready: pick('可推广', 'Promotable'),
    review_required: pick('需复核', 'Needs Review'),
    invalid: pick('禁止自动化', 'Block Automation'),
  };
  return badge(state, labels[state] || fmt(state));
}

function qualityStateText(state) {
  const labels = {
    ready: pick('可推广', 'Promotable'),
    review_required: pick('需复核', 'Needs Review'),
    invalid: pick('禁止自动化', 'Block Automation'),
  };
  return labels[state] || fmt(state);
}

function ratioPct(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '--';
  return fmtPct(number * 100);
}

function noteStack(items) {
  const rows = (items || []).filter(Boolean);
  if (!rows.length) return emptyState(pick('当前没有补充建议。', 'No follow-up notes right now.'));
  return `<div class="ops-note-stack">${rows.map((item) => `<div class="guard-note">${escapeHtml(item)}</div>`).join('')}</div>`;
}

function renderQualityLab(data) {
  const detector = data.detector || {};
  const badgeOcr = data.badge_ocr || {};
  const face = data.face_identity || {};
  const thresholds = data.thresholds || {};
  const activeMetrics = detector.active_run?.metrics || {};
  return sectionBlock('quality-lab', pick('识别质量实验室', 'Recognition Quality Lab'), `
    <section class="metric-grid">
      ${metricCard(pick('Detector 状态', 'Detector Status'), qualityStateText(detector.state), pick('当前安全帽检测推广状态', 'Current detector promotion posture'), detector.state === 'ready' ? 'success' : detector.state === 'invalid' ? 'danger' : 'warning')}
      ${metricCard(pick('工牌 OCR', 'Badge OCR'), ratioPct(badgeOcr.coverage_rate), pick('工牌关键词覆盖率', 'Badge keyword coverage'), badgeOcr.state === 'ready' ? 'success' : badgeOcr.state === 'invalid' ? 'danger' : 'warning')}
      ${metricCard(pick('人脸样本', 'Face Coverage'), ratioPct(face.coverage_rate), pick('现场脸图覆盖率', 'On-site face coverage'), face.state === 'ready' ? 'success' : face.state === 'invalid' ? 'danger' : 'warning')}
      ${metricCard(pick('硬例池', 'Hard Cases'), fmt(detector.hard_cases_total), pick('用于回放和重训的难例样本', 'Hard cases available for replay and retraining'), Number(detector.hard_cases_total) > 12 ? 'warning' : '')}
      ${metricCard(pick('当前 detector 阈值', 'Detector Threshold'), `${fmt(thresholds.detector_confidence)} / ${fmt(thresholds.alert_confidence)}`, pick('检测阈值 / 触发告警阈值', 'Detection / alert trigger thresholds'))}
    </section>
    <div class="two-col">
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('安全帽检测', 'Helmet Detector')}</div><div class="table-sub">${pick('先看站点 holdout 指标，再决定是否推广。', 'Review the site holdout posture before promotion.')}</div></div>${qualityStateBadge(detector.state)}</div>
        <div class="table-body">
          <div class="detail-list" style="margin-bottom:14px">
            <div class="detail-item"><div class="detail-key">${pick('当前模型', 'Active model')}</div><div class="detail-value">${escapeHtml(fmt(detector.active_model || '--'))}</div></div>
            <div class="detail-item"><div class="detail-key">Precision / Recall / F1</div><div class="detail-value">${escapeHtml(`${fmt(activeMetrics.precision)} / ${fmt(activeMetrics.recall)} / ${fmt(activeMetrics.f1)}`)}</div></div>
            <div class="detail-item"><div class="detail-key">mAP50 / mAP50-95</div><div class="detail-value">${escapeHtml(`${fmt(activeMetrics.map50)} / ${fmt(activeMetrics.map50_95)}`)}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('建议阈值', 'Recommended thresholds')}</div><div class="detail-value">${escapeHtml(`${fmt(detector.recommended_confidence)} / ${fmt(detector.recommended_alert_confidence)}`)}</div></div>
          </div>
          ${noteStack(detector.notes)}
        </div>
      </div>
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('身份自动化', 'Identity Automation')}</div><div class="table-sub">${pick('高自动化只建立在高置信证据之上。', 'High automation only ships on high-confidence evidence.')}</div></div></div>
        <div class="table-body">
          <div class="detail-list" style="margin-bottom:14px">
            <div class="detail-item"><div class="detail-key">${pick('工牌 OCR', 'Badge OCR')}</div><div class="detail-value">${qualityStateBadge(badgeOcr.state)}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('OCR 阈值', 'OCR threshold')}</div><div class="detail-value">${escapeHtml(`${fmt(badgeOcr.thresholds?.current)} -> ${fmt(badgeOcr.thresholds?.recommended)}`)}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('人脸识别', 'Face identity')}</div><div class="detail-value">${qualityStateBadge(face.state)}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('相似度阈值', 'Similarity thresholds')}</div><div class="detail-value">${escapeHtml(`${fmt(face.thresholds?.similarity)} / ${fmt(face.thresholds?.review)} -> ${fmt(face.thresholds?.recommended_similarity)} / ${fmt(face.thresholds?.recommended_review)}`)}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('Top-1 margin', 'Top-1 margin')}</div><div class="detail-value">${escapeHtml(fmt(face.thresholds?.recommended_top1_margin))}</div></div>
          </div>
          ${noteStack([...(badgeOcr.notes || []), ...(face.notes || [])])}
        </div>
      </div>
    </div>
    <div class="two-col">
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('最近 benchmark 运行', 'Latest Benchmark Runs')}</div><div class="table-sub">${pick('用真实训练结果而不是口头判断。', 'Use real training outputs instead of guesswork.')}</div></div></div>
        <div class="table-body">${table(
          [pick('运行', 'Run'), 'P / R / F1', 'mAP50', pick('时间', 'Updated')],
          data.latest_benchmark_runs || [],
          (item) => `<tr>
            <td>${escapeHtml(item.run_id || '--')}</td>
            <td>${escapeHtml(`${fmt(item.metrics?.precision)} / ${fmt(item.metrics?.recall)} / ${fmt(item.metrics?.f1)}`)}</td>
            <td>${escapeHtml(fmt(item.metrics?.map50))}</td>
            <td>${escapeHtml(fmtTime(item.updated_at))}</td>
          </tr>`,
        )}</div>
      </div>
      <div class="table-panel">
        <div class="table-header"><div><div class="table-title">${pick('质量产物与下一步', 'Quality Outputs and Next Steps')}</div><div class="table-sub">${pick('这轮结论和建议都会落到 artifacts 里。', 'This round writes its findings back into artifacts.')}</div></div></div>
        <div class="table-body">
          <div class="detail-list" style="margin-bottom:14px">
            <div class="detail-item"><div class="detail-key">${pick('JSON 摘要', 'JSON summary')}</div><div class="detail-value">${escapeHtml(fmt(data.artifacts?.summary_json || '--'))}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('Markdown 报告', 'Markdown report')}</div><div class="detail-value">${escapeHtml(fmt(data.artifacts?.summary_markdown || '--'))}</div></div>
            <div class="detail-item"><div class="detail-key">${pick('硬例拆分', 'Hard-case breakdown')}</div><div class="detail-value">${escapeHtml(`${fmt(detector.hard_case_breakdown?.false_positive, '0')} FP / ${fmt(detector.hard_case_breakdown?.missed_detection, '0')} Miss / ${fmt(detector.hard_case_breakdown?.night, '0')} Night`)}</div></div>
          </div>
          ${noteStack(data.next_actions)}
        </div>
      </div>
    </div>
  `);
}

function renderBackupRelease(backups, releases) {
  return sectionBlock('backup-release', pick('备份与发布', 'Backup and Release'), `
    <section class="metric-grid">
      ${metricCard(pick('备份总数', 'Backups'), fmt(backups.count), pick('可回滚的备份档案', 'Backup archives'))}
      ${metricCard(pick('当前激活发布', 'Active Release'), fmt(releases.active_release || '--'), pick('当前使用的配置快照', 'Current release snapshot'))}
      ${metricCard(pick('发布快照', 'Releases'), fmt((releases.releases || []).length), pick('已创建的配置快照', 'Saved release snapshots'))}
      ${metricCard(pick('注册模型', 'Models'), fmt((releases.models || []).length), pick('模型注册表记录数', 'Model registry rows'))}
      ${metricCard(pick('激活模型', 'Active Model'), fmt(releases.active_model || '--'), pick('当前激活模型', 'Current active model'))}
    </section>
    ${canAdmin() ? `<div class="inline-actions" style="margin-bottom:14px"><button class="btn btn-ghost" id="ops-create-backup">${pick('创建备份', 'Create Backup')}</button><button class="btn btn-ghost" id="ops-create-release">${pick('创建发布快照', 'Create Snapshot')}</button><button class="btn btn-danger" id="ops-rollback-release">${pick('执行回滚', 'Rollback')}</button></div>` : ''}
    <div class="two-col">
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('备份档案', 'Backups')}</div></div></div><div class="table-body">${table(
        [pick('备份名', 'Backup'), pick('文件数', 'Files'), pick('时间', 'Time'), pick('操作', 'Action')],
        backups.items || [],
        (item) => `<tr>
          <td>${escapeHtml(item.backup_name || '--')}</td>
          <td>${escapeHtml(fmt(item.file_count))}</td>
          <td>${escapeHtml(fmtTime(item.created_at))}</td>
          <td>${canAdmin() ? `<button class="btn btn-ghost btn-sm" data-restore-backup="${escapeHtml(item.backup_path || '')}">${pick('恢复', 'Restore')}</button>` : '--'}</td>
        </tr>`,
      )}</div></div>
      <div class="table-panel"><div class="table-header"><div><div class="table-title">${pick('发布快照', 'Release Snapshots')}</div></div></div><div class="table-body">${table(
        [pick('发布名', 'Release'), pick('类型', 'Kind'), pick('时间', 'Time'), pick('操作', 'Action')],
        releases.releases || [],
        (item) => `<tr>
          <td>${escapeHtml(item.release_name || '--')}</td>
          <td>${escapeHtml(item.release_kind || '--')}</td>
          <td>${escapeHtml(fmtTime(item.created_at))}</td>
          <td>${canAdmin() ? `<button class="btn btn-ghost btn-sm" data-activate-release="${escapeHtml(item.release_name || '')}">${pick('激活', 'Activate')}</button>` : '--'}</td>
        </tr>`,
      )}</div></div>
    </div>
  `);
}

function renderNotifications(logs) {
  return sectionBlock('notifications', pick('通知中心', 'Notifications'), `
    ${canAdmin() ? `<div class="inline-actions" style="margin-bottom:14px"><button class="btn btn-ghost" id="ops-test-email">${pick('发送测试邮件', 'Send Test Email')}</button></div>` : ''}
    ${table(
      [pick('事件', 'Event'), pick('接收人', 'Recipient'), pick('通道', 'Channel'), pick('状态', 'Status'), pick('时间', 'Time')],
      logs.items || [],
      (item) => `<tr><td>${escapeHtml(item.event_no || item.alert_id || '--')}</td><td>${escapeHtml(item.recipient || '--')}</td><td>${escapeHtml(item.channel || '--')}</td><td>${badge(item.status)}</td><td>${escapeHtml(fmtTime(item.created_at))}</td></tr>`,
    )}
  `);
}

function renderAccessAdmin(accounts) {
  const user = getAuthUser();
  return sectionBlock('access-admin', pick('账号管理', 'Access Administration'), `
    <section class="metric-grid">
      ${metricCard(pick('账号总数', 'Total Accounts'), fmt((accounts.items || []).length), pick('当前可登录账号', 'Accounts able to sign in'))}
      ${metricCard('Admin', fmt((accounts.items || []).filter((item) => item.role === 'admin').length), pick('管理员账号', 'Administrator accounts'))}
      ${metricCard('Manager', fmt((accounts.items || []).filter((item) => item.role === 'safety_manager').length), pick('安全经理角色', 'Safety manager role'))}
      ${metricCard('Viewer', fmt((accounts.items || []).filter((item) => item.role === 'viewer').length), pick('只读角色', 'Read-only role'))}
      ${metricCard(pick('当前账号', 'Current User'), fmt(user.username), pick('正在使用的账号', 'Current signed-in account'))}
    </section>
    ${canAdmin() ? `<div class="inline-actions" style="margin-bottom:14px"><button class="btn btn-ghost" id="ops-add-account">${pick('新建账号', 'New Account')}</button><button class="btn btn-ghost" id="ops-change-password">${pick('修改当前密码', 'Change Current Password')}</button></div>` : ''}
    ${table(
      [pick('账号', 'Username'), pick('角色', 'Role'), pick('名称', 'Display Name'), pick('邮箱', 'Email'), pick('来源', 'Source')],
      accounts.items || [],
      (item) => `<tr><td>${escapeHtml(item.username || '--')}</td><td>${badge(item.role, item.role || '--')}</td><td>${escapeHtml(item.display_name || '--')}</td><td>${escapeHtml(item.email || '--')}</td><td>${escapeHtml(item.source || '--')}</td></tr>`,
    )}
  `);
}

function renderRuntimeModes(data) {
  return sectionBlock('runtime-modes', pick('运行模式', 'Runtime Modes'), `
    ${table(
      [pick('模式', 'Mode'), pick('可用', 'Available'), pick('入口', 'Entry'), pick('说明', 'Description')],
      data.runtime_modes || [],
      (item) => `<tr><td>${escapeHtml(item.label || '--')}</td><td>${badge(item.available ? 'ready' : 'missing', item.available ? pick('可用', 'Available') : pick('不可用', 'Unavailable'))}</td><td>${escapeHtml(item.entry || '--')}</td><td>${escapeHtml(item.description || '--')}</td></tr>`,
    )}
  `);
}

function scrollToRequestedSection(container) {
  const section = currentSection();
  const target = container.querySelector(`#ops-${CSS.escape(section)}`);
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function executeServiceAction(serviceName, action) {
  const confirmText = promptConfirmText(`${pick('服务操作', 'Service action')}: ${serviceName} / ${action}`);
  if (!confirmText) return;
  const result = await api.ops.serviceAction(serviceName, { action, confirm_text: confirmText });
  toast.success(pick('服务操作已提交', 'Service action submitted'), `${result.service_name} / ${result.action}`);
}

async function executeRestoreBackup(backupPath) {
  const confirmText = promptConfirmText(pick('恢复备份', 'Restore backup'));
  if (!confirmText) return;
  const result = await api.ops.restoreBackup({ backup_path: backupPath, confirm_text: confirmText });
  toast.success(pick('备份恢复已执行', 'Backup restore completed'), escapeHtml(result.backup_path || ''));
}

async function executeActivateRelease(releaseName) {
  const confirmText = promptConfirmText(`${pick('激活发布', 'Activate release')}: ${releaseName}`);
  if (!confirmText) return;
  const result = await api.ops.activateRelease({ release_name: releaseName, confirm_text: confirmText });
  toast.success(pick('发布已激活', 'Release activated'), result.release_name);
}

async function bindActions(container) {
  container.querySelectorAll('[data-service-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const [serviceName, action] = String(button.getAttribute('data-service-action') || '').split(':');
      try {
        await executeServiceAction(serviceName, action);
        await render(container);
      } catch (error) {
        toast.error(pick('服务操作失败', 'Service action failed'), error.message);
      }
    });
  });
  container.querySelector('#ops-identity-sync')?.addEventListener('click', async () => {
    try {
      const result = await api.ops.identitySync();
      toast.success(pick('登记同步完成', 'Registry sync completed'), result.detail || '');
      await render(container);
    } catch (error) {
      toast.error(pick('同步失败', 'Sync failed'), error.message);
    }
  });
  container.querySelector('#ops-identity-preview')?.addEventListener('click', async () => {
    try {
      await api.ops.identityBootstrap({ apply: false, overwrite: false });
      toast.success(pick('已刷新默认绑定建议', 'Default binding preview refreshed'));
      await render(container);
    } catch (error) {
      toast.error(pick('预览失败', 'Preview failed'), error.message);
    }
  });
  container.querySelector('#ops-identity-apply')?.addEventListener('click', async () => {
    try {
      const result = await api.ops.identityBootstrap({ apply: true, overwrite: false });
      toast.success(pick('默认绑定建议已应用', 'Default bindings applied'), `${fmt(result.updated_defaults)} updated`);
      await render(container);
    } catch (error) {
      toast.error(pick('应用失败', 'Apply failed'), error.message);
    }
  });
  container.querySelector('#ops-validate-storage')?.addEventListener('click', async () => {
    try {
      await api.ops.validateStorage({});
      toast.success(pick('存储验证完成', 'Storage validation completed'));
      await render(container);
    } catch (error) {
      toast.error(pick('验证失败', 'Validation failed'), error.message);
    }
  });
  container.querySelector('#ops-validate-notification')?.addEventListener('click', async () => {
    try {
      await api.ops.validateNotification({});
      toast.success(pick('通知验证完成', 'Notification validation completed'));
      await render(container);
    } catch (error) {
      toast.error(pick('验证失败', 'Validation failed'), error.message);
    }
  });
  container.querySelector('#ops-export-feedback')?.addEventListener('click', async () => {
    try {
      await api.ops.exportFeedback({ limit: 100 });
      toast.success(pick('反馈导出完成', 'Feedback export completed'));
      await render(container);
    } catch (error) {
      toast.error(pick('导出失败', 'Export failed'), error.message);
    }
  });
  container.querySelector('#ops-build-dataset')?.addEventListener('click', async () => {
    try {
      await api.ops.buildFeedbackDataset({});
      toast.success(pick('反馈数据集已生成', 'Feedback dataset generated'));
      await render(container);
    } catch (error) {
      toast.error(pick('构建失败', 'Build failed'), error.message);
    }
  });
  container.querySelector('#ops-create-backup')?.addEventListener('click', async () => {
    try {
      await api.ops.createBackup({});
      toast.success(pick('备份已创建', 'Backup created'));
      await render(container);
    } catch (error) {
      toast.error(pick('备份失败', 'Backup failed'), error.message);
    }
  });
  container.querySelector('#ops-create-release')?.addEventListener('click', async () => {
    try {
      await api.ops.createReleaseSnapshot({});
      toast.success(pick('发布快照已创建', 'Release snapshot created'));
      await render(container);
    } catch (error) {
      toast.error(pick('创建失败', 'Create failed'), error.message);
    }
  });
  container.querySelector('#ops-rollback-release')?.addEventListener('click', async () => {
    try {
      const confirmText = promptConfirmText(pick('执行发布回滚', 'Execute release rollback'));
      if (!confirmText) return;
      await api.ops.rollbackRelease({ steps: 1, confirm_text: confirmText });
      toast.success(pick('已执行回滚', 'Rollback completed'));
      await render(container);
    } catch (error) {
      toast.error(pick('回滚失败', 'Rollback failed'), error.message);
    }
  });
  container.querySelectorAll('[data-restore-backup]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await executeRestoreBackup(button.getAttribute('data-restore-backup') || '');
        await render(container);
      } catch (error) {
        toast.error(pick('恢复失败', 'Restore failed'), error.message);
      }
    });
  });
  container.querySelectorAll('[data-activate-release]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await executeActivateRelease(button.getAttribute('data-activate-release') || '');
        await render(container);
      } catch (error) {
        toast.error(pick('激活失败', 'Activate failed'), error.message);
      }
    });
  });
  container.querySelector('#ops-test-email')?.addEventListener('click', async () => {
    const recipient = window.prompt(pick('输入测试收件人邮箱', 'Enter test recipient email'), '');
    if (!recipient) return;
    try {
      await api.notifications.test({ recipient, subject: 'Safety Helmet System Test', body: 'This is a test email from the Safety Helmet Command Center.' });
      toast.success(pick('测试邮件已发送', 'Test email sent'));
      await render(container);
    } catch (error) {
      toast.error(pick('发送失败', 'Send failed'), error.message);
    }
  });
  container.querySelector('#ops-add-account')?.addEventListener('click', async () => {
    const username = window.prompt(pick('输入新账号用户名', 'Enter username'), '');
    if (!username) return;
    const password = window.prompt(pick('输入初始密码，至少 8 位', 'Enter initial password, at least 8 chars'), '');
    if (!password) return;
    try {
      await api.accounts.save({ username, password, role: 'viewer', display_name: username, email: username });
      toast.success(pick('账号已创建', 'Account created'));
      await render(container);
    } catch (error) {
      toast.error(pick('创建失败', 'Create failed'), error.message);
    }
  });
  container.querySelector('#ops-change-password')?.addEventListener('click', async () => {
    const password = window.prompt(pick('输入新的当前账号密码', 'Enter the new password for the current account'), '');
    if (!password) return;
    try {
      await api.auth.changePassword({ new_password: password });
      toast.success(pick('密码已修改，请重新登录', 'Password changed. Please sign in again.'));
      clearAuth();
      window.location.hash = '#/login';
    } catch (error) {
      toast.error(pick('修改失败', 'Change failed'), error.message);
    }
  });
}

export async function render(container) {
  const user = getAuthUser();
  if (!isAuthenticated() || !(user.routes || []).includes('/operations')) {
    container.innerHTML = `${shell()}${emptyState(pick('运维工作台需要管理员或安全经理登录。', 'Operations Studio requires an elevated login.'), pick('访客模式和只读角色不能进入运维工作台。', 'Guest mode and low-privilege roles cannot access Operations Studio.'))}`;
    markPageReady(container, 'operations');
    return;
  }

  container.innerHTML = `${shell()}${emptyState(pick('正在加载运维工作台', 'Loading Operations Studio'))}`;
  try {
    const results = await Promise.allSettled([
      api.ops.capabilities(),
      api.ops.readiness(),
      api.ops.services(),
      api.ops.identitySummary(),
      api.ops.evidenceDelivery(),
      api.ops.modelFeedback(),
      api.ops.qualitySummary(),
      api.ops.backups(),
      api.ops.releases(),
      api.notifications.list(),
      user.role === 'admin' ? api.accounts.list() : Promise.resolve({ items: [] }),
    ]);

    const [
      capabilities,
      readiness,
      services,
      identity,
      evidenceDelivery,
      modelFeedback,
      qualitySummary,
      backups,
      releases,
      notifications,
      accounts,
    ] = results.map((item) => item.status === 'fulfilled' ? item.value : { items: [], checks: [], services: {}, runtime_modes: [], summary: {}, coverage_errors: [], metrics: {}, releases: [], activation_history: [], active_release: null, latest_benchmark_runs: [], next_actions: [] });

    const active = currentSection();
    container.innerHTML = `${shell(`<button class="btn btn-ghost" id="refresh-operations">${pick('刷新工作台', 'Refresh Studio')}</button>`)}
      ${sectionTabs(active)}
      <div class="ops-studio-stack">
        ${renderCoverage(capabilities)}
        ${renderReadiness(readiness)}
        ${renderServices(services)}
        ${renderIdentity(identity)}
        ${renderEvidenceDelivery(evidenceDelivery)}
        ${renderModelFeedback(modelFeedback)}
        ${renderQualityLab(qualitySummary)}
        ${renderBackupRelease(backups, releases)}
        ${renderNotifications(notifications)}
        ${renderAccessAdmin(accounts)}
        ${renderRuntimeModes(services)}
      </div>`;

    container.querySelector('#refresh-operations')?.addEventListener('click', () => render(container));
    await bindActions(container);
    markPageReady(container, 'operations');
    requestAnimationFrame(() => scrollToRequestedSection(container));
  } catch (error) {
    container.innerHTML = `${shell(`<button class="btn btn-ghost" id="retry-operations">${pick('重试', 'Retry')}</button>`)}${emptyState(pick('运维工作台接口暂不可用', 'Operations Studio API unavailable'), error.message)}`;
    container.querySelector('#retry-operations')?.addEventListener('click', () => render(container));
    markPageReady(container, 'operations');
  }
}
