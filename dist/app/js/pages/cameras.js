import { api, assetUrl, getAuthUser } from '../api.js?v=1';
import { pick } from '../i18n.js?v=1';
import { createRealtimeChannel } from '../realtime.js?v=1';
import { badge, emptyState, escapeHtml, fmt, fmtTime, markPageReady, metricCard, pageHeader, statusLabel } from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

let cameras = [];
let selectedCameraId = '';
let browserStream = null;
let inferTimer = 0;
let overlayRaf = 0;
let latestDetections = [];
let latestFrameWidth = 0;
let latestFrameHeight = 0;
let latestInferMs = 0;
let latestDetectionAt = 0;
let frameRefreshTimer = 0;
const frameObjectUrls = new Map();
const frameControllers = new Set();
const MAX_LIVE_FRAME_FETCHES = 8;
let realtimeChannel = null;
let liveReloadTimer = 0;

function selectedCamera() {
  return cameras.find((item) => item.camera_id === selectedCameraId) || cameras[0] || null;
}

function sourceKindLabel(value) {
  const map = {
    local_device: pick('本地设备', 'Local Device'),
    env_placeholder: pick('环境占位符', 'Env Placeholder'),
    env_reference: pick('环境引用', 'Env Reference'),
    remote_stream: pick('远程流', 'Remote Stream'),
    local_path: pick('本地路径', 'Local Path'),
    unknown: pick('未知', 'Unknown'),
  };
  return map[String(value || '')] || fmt(value);
}

function stopBrowserPreview() {
  if (inferTimer) window.clearTimeout(inferTimer);
  if (overlayRaf) cancelAnimationFrame(overlayRaf);
  inferTimer = 0;
  overlayRaf = 0;
  latestDetections = [];
  if (browserStream) {
    browserStream.getTracks().forEach((track) => track.stop());
    browserStream = null;
  }
}

function clearFrameObjectUrls() {
  frameObjectUrls.forEach((url) => URL.revokeObjectURL(url));
  frameObjectUrls.clear();
}

function stopFrameRefresh() {
  if (frameRefreshTimer) window.clearInterval(frameRefreshTimer);
  frameRefreshTimer = 0;
  frameControllers.forEach((controller) => controller.abort());
  frameControllers.clear();
}

function showFrameFallback(img, title, copy) {
  const shell = img.closest('.live-image-shell');
  const fallback = shell?.querySelector('.live-fallback');
  if (fallback) {
    const titleNode = fallback.querySelector('.live-fallback__title');
    const copyNode = fallback.querySelector('.live-fallback__copy');
    if (titleNode && title) titleNode.textContent = title;
    if (copyNode && copy) copyNode.textContent = copy;
    fallback.style.display = 'grid';
  }
  img.hidden = true;
}

async function loadLiveFrame(img) {
  const frameUrl = img.getAttribute('data-frame-url');
  const cameraId = img.getAttribute('data-live-frame') || frameUrl;
  if (!frameUrl || document.hidden) return;
  const controller = new AbortController();
  frameControllers.add(controller);
  try {
    const response = await fetch(`${assetUrl(frameUrl)}?t=${Date.now()}`, { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    if (!blob.type || !blob.type.toLowerCase().includes('image')) throw new Error('Invalid image response');
    const oldUrl = frameObjectUrls.get(cameraId);
    if (oldUrl) URL.revokeObjectURL(oldUrl);
    const objectUrl = URL.createObjectURL(blob);
    frameObjectUrls.set(cameraId, objectUrl);
    img.onload = () => {
      const fallback = img.closest('.live-image-shell')?.querySelector('.live-fallback');
      if (fallback) fallback.style.display = 'none';
      img.hidden = false;
    };
    img.onerror = () => showFrameFallback(
      img,
      pick('实时帧读取失败', 'Live frame failed'),
      pick('后端帧可能已经过期，刷新后会重新拉取。', 'The backend frame may be stale. Refresh to retry.'),
    );
    img.src = objectUrl;
  } catch (error) {
    if (error.name === 'AbortError') return;
    showFrameFallback(
      img,
      pick('实时帧读取失败', 'Live frame failed'),
      pick('后端帧可能已经过期，刷新后会重新拉取。', 'The backend frame may be stale. Refresh to retry.'),
    );
  } finally {
    frameControllers.delete(controller);
  }
}

function refreshLiveFrames(container) {
  Array.from(container.querySelectorAll('.live-frame-img[data-frame-url]'))
    .slice(0, MAX_LIVE_FRAME_FETCHES)
    .forEach((img) => loadLiveFrame(img));
}

function scheduleFrameRefresh(container) {
  stopFrameRefresh();
  refreshLiveFrames(container);
  frameRefreshTimer = window.setInterval(() => refreshLiveFrames(container), 5000);
}

function locationText(item) {
  return [item.site_name, item.building_name, item.floor_name, item.zone_name].filter(Boolean).join(' / ') || item.location || '--';
}

function liveFallback(item, compact = false) {
  const reason = item?.display_group === 'disabled'
    ? pick('该摄像头在运行配置中已禁用，但仍保留入口方便排查。', 'This camera is disabled in runtime config, but the entry stays visible for inspection.')
    : item?.last_error || pick('等待 monitor 写入最新画面，或启动浏览器本机预览。', 'Waiting for monitor frames, or start browser local preview.');
  return `<div class="live-fallback ${compact ? 'compact' : ''}">
    <div>
      <div class="live-fallback__title">${pick('暂无实时画面', 'No live frame yet')}</div>
      <div class="live-fallback__copy">${escapeHtml(reason)}</div>
    </div>
  </div>`;
}

function liveImage(item, compact = false) {
  if (!item?.has_live_frame || !item.frame_url) return liveFallback(item, compact);
  return `<div class="live-image-shell ${compact ? 'compact' : ''}">
    <img class="live-frame-img" data-live-frame="${escapeHtml(item.camera_id)}" data-frame-url="${escapeHtml(item.frame_url)}" alt="${escapeHtml(item.camera_name || item.camera_id)}" loading="eager" hidden>
    <div class="live-fallback ${compact ? 'compact' : ''}">
      <div>
        <div class="live-fallback__title">${pick('实时帧读取失败', 'Live frame failed')}</div>
        <div class="live-fallback__copy">${pick('后端帧可能已经过期，刷新后会重新拉取。', 'The backend frame may be stale. Refresh to retry.')}</div>
      </div>
    </div>
  </div>`;
}

function selectorButton(item) {
  const tone = item.display_group === 'disabled'
    ? 'disabled'
    : item.has_live_frame
      ? 'ready'
      : item.last_status || 'missing';
  return `<button class="camera-selector ${item.camera_id === selectedCameraId ? 'active' : ''} ${item.display_group === 'disabled' ? 'muted' : ''}" data-select-camera="${escapeHtml(item.camera_id)}" type="button">
    <span class="camera-selector__name">${escapeHtml(item.camera_name || item.camera_id || '--')}</span>
    <span class="camera-selector__meta">${escapeHtml(statusLabel(tone))}</span>
  </button>`;
}

function stageStatusCopy(item) {
  if (!item) return pick('暂无摄像头可展示。', 'No cameras available.');
  if (item.browser_preview_supported) {
    return pick('当前可切换为浏览器本机预览，不保存视频。', 'This camera can switch to browser local preview without storing video.');
  }
  return pick('当前显示后端代理的最新画面，不暴露原始流地址。', 'This stage shows the latest backend-proxied frame without exposing raw stream URLs.');
}

function mainStage(item) {
  if (!item) return `<section class="visual-panel">${emptyState(pick('暂无摄像头', 'No cameras'))}</section>`;
  const overlayMessage = item.has_live_frame
    ? ''
    : (item.browser_preview_supported
      ? pick('点击启动预览并授权摄像头。', 'Start preview and allow camera access.')
      : stageStatusCopy(item));
  return `<section class="visual-panel live-stage-panel">
    <div class="visual-header">
      <div>
        <div class="visual-title">${escapeHtml(item.camera_name || item.camera_id || '--')}</div>
        <div class="visual-sub">${escapeHtml(stageStatusCopy(item))}</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-ghost btn-sm" id="refresh-selected-frame">${pick('刷新画面', 'Refresh Frame')}</button>
        <button class="btn btn-primary btn-sm" id="start-browser-preview" ${item.browser_preview_supported ? '' : 'disabled'}>${pick('启动预览', 'Start Preview')}</button>
        <button class="btn btn-ghost btn-sm" id="stop-browser-preview">${pick('停止', 'Stop')}</button>
      </div>
    </div>
    <div class="visual-body">
      <div class="live-stage-meta">
        <div><span>${pick('状态', 'Status')}</span><strong>${escapeHtml(statusLabel(item.last_status || 'configured'))}</strong></div>
        <div><span>${pick('来源类型', 'Source Kind')}</span><strong>${escapeHtml(sourceKindLabel(item.source_kind))}</strong></div>
        <div><span>FPS</span><strong>${escapeHtml(fmt(item.last_fps))}</strong></div>
        <div><span>${pick('最近帧', 'Latest Frame')}</span><strong>${escapeHtml(fmtTime(item.frame_updated_at || item.preview_updated_at || item.last_frame_at))}</strong></div>
      </div>
      <div class="browser-preview-shell live-stage-shell">
        <div class="live-stage-feed">${liveImage(item)}</div>
        <video id="browser-preview-video" autoplay playsinline muted hidden></video>
        <canvas id="browser-preview-overlay" hidden></canvas>
        <div id="browser-preview-status" class="browser-preview-status" ${item.has_live_frame ? 'style="display:none"' : ''}>${escapeHtml(overlayMessage)}</div>
      </div>
    </div>
  </section>`;
}

function cameraCard(item) {
  return `<article class="live-camera-card" data-live-camera-id="${escapeHtml(item.camera_id)}">
    <div class="live-camera-media">${liveImage(item, true)}</div>
    <div class="live-camera-body">
      <div class="live-camera-title-row">
        <div>
          <div class="live-camera-title">${escapeHtml(item.camera_name || item.camera_id || '--')}</div>
          <div class="live-camera-sub">${escapeHtml(locationText(item))}</div>
        </div>
        ${badge(item.display_group === 'disabled' ? 'disabled' : (item.last_status || 'configured'))}
      </div>
      <div class="live-camera-meta">
        <div><span>${pick('部门', 'Dept')}</span><strong>${escapeHtml(item.department || '--')}</strong></div>
        <div><span>FPS</span><strong>${escapeHtml(fmt(item.last_fps))}</strong></div>
        <div><span>${pick('最新帧', 'Frame')}</span><strong>${escapeHtml(fmtTime(item.frame_updated_at || item.preview_updated_at || item.last_frame_at))}</strong></div>
      </div>
      ${item.last_error ? `<div class="guard-note">${escapeHtml(item.last_error)}</div>` : ''}
      <div class="live-camera-actions">
        <button class="btn btn-ghost btn-sm" data-select-camera="${escapeHtml(item.camera_id)}">${pick('查看主画面', 'View Main Stage')}</button>
        <button class="btn btn-primary btn-sm" data-browser-preview="${escapeHtml(item.camera_id)}" ${item.browser_preview_supported ? '' : 'disabled'}>${pick('浏览器预览', 'Browser Preview')}</button>
      </div>
    </div>
  </article>`;
}

function shell(actionHtml = '') {
  const user = getAuthUser();
  const opsLink = (user.routes || []).includes('/operations')
    ? `<a class="btn btn-ghost" href="#/operations">${pick('运维工作台', 'Operations Studio')}</a>`
    : '';
  return pageHeader(
    'LIVE CAMERA OPS',
    pick('摄像头现场', 'Live Cameras'),
    pick('顶部入口覆盖全部配置摄像头，主画面聚焦当前选中的实时流。', 'Top selectors cover every configured camera while the main stage focuses on the current live feed.'),
    `${actionHtml}${opsLink}`,
  );
}

function drawOverlay(video, canvas) {
  const ctx = canvas.getContext('2d');
  const resize = () => {
    const width = canvas.clientWidth || video.clientWidth || 1;
    const height = canvas.clientHeight || video.clientHeight || 1;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  };
  const draw = () => {
    resize();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (latestFrameWidth && latestFrameHeight && Date.now() - latestDetectionAt < 1200) {
      const scaleX = canvas.width / latestFrameWidth;
      const scaleY = canvas.height / latestFrameHeight;
      latestDetections.forEach((item) => {
        const color = item.is_violation ? '#ff3d57' : '#00ff88';
        const x = Number(item.x1 || 0) * scaleX;
        const y = Number(item.y1 || 0) * scaleY;
        const w = Math.max(1, (Number(item.x2 || 0) - Number(item.x1 || 0)) * scaleX);
        const h = Math.max(1, (Number(item.y2 || 0) - Number(item.y1 || 0)) * scaleY);
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
        ctx.strokeRect(x, y, w, h);
        ctx.font = '700 14px Consolas, monospace';
        ctx.fillStyle = color;
        ctx.fillText(item.is_violation ? 'No Helmet' : 'Helmet', x, Math.max(18, y - 6));
      });
    }
    ctx.font = '13px Consolas, monospace';
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text-primary').trim();
    ctx.fillText(`Infer ${Math.round(latestInferMs)} ms`, 14, 24);
    overlayRaf = requestAnimationFrame(draw);
  };
  draw();
}

async function startBrowserPreview(container) {
  const item = selectedCamera();
  if (!item?.browser_preview_supported) return;
  const status = container.querySelector('#browser-preview-status');
  const video = container.querySelector('#browser-preview-video');
  const overlay = container.querySelector('#browser-preview-overlay');
  const captureCanvas = document.createElement('canvas');
  const captureCtx = captureCanvas.getContext('2d', { alpha: false });
  stopBrowserPreview();
  video.hidden = false;
  overlay.hidden = false;
  try {
    status.textContent = pick('正在请求摄像头权限...', 'Requesting camera permission...');
    status.style.display = 'grid';
    browserStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 24, max: 30 } },
      audio: false,
    });
    video.srcObject = browserStream;
    await video.play();
    status.style.display = 'none';
    drawOverlay(video, overlay);
  } catch (error) {
    status.style.display = 'grid';
    status.textContent = pick('摄像头权限被拒绝或设备不可用。', 'Camera permission was denied or the device is unavailable.');
    video.hidden = true;
    overlay.hidden = true;
    toast.warning(pick('摄像头不可用', 'Camera unavailable'), error.message);
    return;
  }

  const runInference = async () => {
    if (!browserStream || document.hidden || video.readyState < 2 || !video.videoWidth) {
      inferTimer = window.setTimeout(runInference, 350);
      return;
    }
    const maxWidth = 640;
    let width = video.videoWidth;
    let height = video.videoHeight;
    if (width > maxWidth) {
      height = Math.max(1, Math.round(height * (maxWidth / width)));
      width = maxWidth;
    }
    captureCanvas.width = width;
    captureCanvas.height = height;
    captureCtx.drawImage(video, 0, 0, width, height);
    const started = performance.now();
    captureCanvas.toBlob(async (blob) => {
      if (!blob) {
        inferTimer = window.setTimeout(runInference, 450);
        return;
      }
      try {
        const response = await fetch(assetUrl(item.browser_infer_url), {
          method: 'POST',
          headers: { 'Content-Type': 'image/jpeg' },
          body: blob,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        latestDetections = Array.isArray(payload.detections) ? payload.detections : [];
        latestFrameWidth = Number(payload.frame_width || width);
        latestFrameHeight = Number(payload.frame_height || height);
        latestInferMs = Number(payload.infer_ms || performance.now() - started);
        latestDetectionAt = Date.now();
      } catch {
        status.style.display = 'grid';
        status.textContent = pick('检测接口正在预热或暂不可用。', 'Detection endpoint is warming up or unavailable.');
      } finally {
        inferTimer = window.setTimeout(runInference, 420);
      }
    }, 'image/jpeg', 0.72);
  };
  runInference();
}

function stopStagePreview(container) {
  stopBrowserPreview();
  const video = container.querySelector('#browser-preview-video');
  const overlay = container.querySelector('#browser-preview-overlay');
  const status = container.querySelector('#browser-preview-status');
  if (video) {
    video.pause();
    video.srcObject = null;
    video.hidden = true;
  }
  if (overlay) overlay.hidden = true;
  if (status) {
    const current = selectedCamera();
    if (current?.has_live_frame) {
      status.style.display = 'none';
    } else {
      status.style.display = 'grid';
      status.textContent = current?.browser_preview_supported
        ? pick('点击启动预览并授权摄像头。', 'Start preview and allow camera access.')
        : stageStatusCopy(current);
    }
  }
}

async function redraw(container) {
  stopFrameRefresh();
  clearFrameObjectUrls();
  const counts = {
    total: cameras.length,
    live: cameras.filter((item) => item.has_live_frame).length,
    browser: cameras.filter((item) => item.browser_preview_supported).length,
    abnormal: cameras.filter((item) => ['offline', 'error', 'failed'].includes(String(item.last_status || '').toLowerCase())).length,
  };
  const current = selectedCamera();
  container.innerHTML = `${shell(`<button class="btn btn-ghost" id="refresh-live-cameras">${pick('刷新', 'Refresh')}</button><a class="btn btn-ghost" href="#/config">${pick('配置中心', 'Config Center')}</a>`)}
    <section class="metric-grid">
      ${metricCard(pick('摄像头', 'Cameras'), fmt(counts.total), pick('当前运行清单', 'Current inventory'))}
      ${metricCard(pick('实时帧', 'Live Frames'), fmt(counts.live), pick('monitor 已写入的最新画面', 'Frames written by monitor'))}
      ${metricCard(pick('本机预览', 'Browser Preview'), fmt(counts.browser), pick('可由浏览器直连的本地设备', 'Local devices available to the browser'))}
      ${metricCard(pick('异常设备', 'Abnormal'), fmt(counts.abnormal), pick('离线或错误状态', 'Offline or error state'), counts.abnormal ? 'danger' : '')}
      ${metricCard(pick('当前选择', 'Current Focus'), escapeHtml(current?.camera_name || '--'), pick('当前正在查看的摄像头', 'Current selected camera'))}
    </section>
    <section class="camera-selector-bar">
      ${(cameras || []).map(selectorButton).join('')}
    </section>
    ${mainStage(current)}
    <section class="live-camera-grid camera-gallery" style="margin-top:14px">
      ${cameras.length ? cameras.map(cameraCard).join('') : emptyState(pick('暂无摄像头', 'No cameras'), pick('请先在配置中心添加摄像头。', 'Add cameras in Config Center first.'))}
    </section>`;

  container.querySelector('#refresh-live-cameras')?.addEventListener('click', () => render(container));
  container.querySelectorAll('[data-select-camera]').forEach((button) => {
    button.addEventListener('click', async () => {
      selectedCameraId = button.getAttribute('data-select-camera') || '';
      stopStagePreview(container);
      await redraw(container);
    });
  });
  container.querySelectorAll('[data-live-camera-id]').forEach((card) => {
    card.addEventListener('click', async (event) => {
      if (event.target.closest('button,a')) return;
      selectedCameraId = card.getAttribute('data-live-camera-id') || '';
      stopStagePreview(container);
      await redraw(container);
    });
  });
  container.querySelectorAll('[data-browser-preview]').forEach((button) => {
    button.addEventListener('click', async () => {
      selectedCameraId = button.getAttribute('data-browser-preview') || '';
      stopStagePreview(container);
      await redraw(container);
      await startBrowserPreview(container);
    });
  });
  container.querySelector('#start-browser-preview')?.addEventListener('click', () => startBrowserPreview(container));
  container.querySelector('#stop-browser-preview')?.addEventListener('click', () => stopStagePreview(container));
  container.querySelector('#refresh-selected-frame')?.addEventListener('click', () => {
    const currentId = selectedCamera()?.camera_id;
    if (!currentId) return;
    const img = container.querySelector(`.live-stage-shell [data-live-frame="${CSS.escape(currentId)}"]`);
    if (img) loadLiveFrame(img);
  });

  scheduleFrameRefresh(container);
  markPageReady(container, 'cameras');
}

export async function render(container) {
  stopBrowserPreview();
  stopFrameRefresh();
  clearFrameObjectUrls();
  container.innerHTML = `${shell()}${emptyState(pick('正在加载摄像头现场', 'Loading live cameras'))}`;
  try {
    const response = await api.cameras.live();
    cameras = response.items || [];
    if (!cameras.some((item) => item.camera_id === selectedCameraId)) selectedCameraId = cameras[0]?.camera_id || '';
    await redraw(container);
    realtimeChannel?.close?.();
    realtimeChannel = createRealtimeChannel('cameras', {
      onMessage(message) {
        if (!['camera_status', 'frame_state'].includes(message?.type)) return;
        if (liveReloadTimer) window.clearTimeout(liveReloadTimer);
        liveReloadTimer = window.setTimeout(() => render(container), 180);
      },
    });
  } catch (error) {
    container.innerHTML = `${shell(`<button class="btn btn-ghost" id="retry-live-cameras">${pick('重试', 'Retry')}</button>`)}${emptyState(pick('摄像头接口暂不可用', 'Live camera API unavailable'), error.message)}`;
    container.querySelector('#retry-live-cameras')?.addEventListener('click', () => render(container));
    markPageReady(container, 'cameras');
  }
}

export function destroy() {
  stopBrowserPreview();
  stopFrameRefresh();
  clearFrameObjectUrls();
  realtimeChannel?.close?.();
  realtimeChannel = null;
  if (liveReloadTimer) window.clearTimeout(liveReloadTimer);
  liveReloadTimer = 0;
}
