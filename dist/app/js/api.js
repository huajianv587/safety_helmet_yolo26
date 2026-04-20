const BASE = (window.__HELMET_API_BASE_URL__ || window.location.origin).replace(/\/+$/, '');

export const GUEST_USER = {
  username: 'guest',
  role: 'viewer',
  display_name: '访客模式',
  email: '',
  permissions: [],
  routes: ['/dashboard', '/review', '/cameras', '/reports', '/hard-cases', '/config'],
};

function token() {
  return localStorage.getItem('helmet-token') || sessionStorage.getItem('helmet-token') || '';
}

export function assetUrl(value) {
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  if (String(value).startsWith('/')) return `${BASE}${value}`;
  return `${BASE}/${String(value).replace(/^\/+/, '')}`;
}

function dispatchAuthChange() {
  window.dispatchEvent(new CustomEvent('auth-change'));
}

function saveAuth(payload, remember) {
  clearAuth(false);
  const storage = remember ? localStorage : sessionStorage;
  storage.setItem('helmet-token', payload.token);
  storage.setItem('helmet-user', JSON.stringify(payload.user));
  dispatchAuthChange();
}

function persistUser(user) {
  if (!token()) return;
  const storage = localStorage.getItem('helmet-token') ? localStorage : sessionStorage;
  storage.setItem('helmet-user', JSON.stringify(user));
}

export function getAuthUser() {
  try {
    const raw = localStorage.getItem('helmet-user') || sessionStorage.getItem('helmet-user');
    return raw ? JSON.parse(raw) : { ...GUEST_USER };
  } catch {
    return { ...GUEST_USER };
  }
}

export function getAuthToken() {
  return token();
}

export function isAuthenticated() {
  return Boolean(token());
}

export function hasPermission(permission) {
  const user = getAuthUser();
  return Array.isArray(user.permissions) && user.permissions.includes(permission);
}

export function clearAuth(emit = true) {
  localStorage.removeItem('helmet-token');
  localStorage.removeItem('helmet-user');
  sessionStorage.removeItem('helmet-token');
  sessionStorage.removeItem('helmet-user');
  if (emit) dispatchAuthChange();
}

function headers(extra = {}) {
  const output = { ...extra };
  const current = token();
  if (current) output.Authorization = `Bearer ${current}`;
  return output;
}

function withQuery(path, params = {}) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== null && item !== '') search.append(key, String(item));
      });
      return;
    }
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function request(method, path, body) {
  const init = { method, headers: headers() };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers = headers({ 'Content-Type': 'application/json' });
    init.body = JSON.stringify(body);
  }

  const response = await fetch(BASE + path, init);
  if (response.status === 204) return null;

  let payload;
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) payload = await response.json();
  else payload = await response.text();

  if (!response.ok) {
    const message = typeof payload === 'string'
      ? payload
      : payload?.detail || payload?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export async function hydrateSession() {
  if (!token()) {
    clearAuth(false);
    dispatchAuthChange();
    return { user: { ...GUEST_USER } };
  }
  try {
    const payload = await request('GET', '/auth/me');
    if (payload?.user) {
      persistUser(payload.user);
      dispatchAuthChange();
    }
    return payload;
  } catch (error) {
    clearAuth();
    return { user: { ...GUEST_USER }, error };
  }
}

function overviewParams(daysOrParams) {
  if (typeof daysOrParams === 'number' || typeof daysOrParams === 'string') return { days: daysOrParams };
  return daysOrParams || {};
}

function reportSummaryParams(daysOrParams, extra = {}) {
  const base = typeof daysOrParams === 'number' || typeof daysOrParams === 'string'
    ? { days: daysOrParams }
    : (daysOrParams || {});
  return { ...base, ...extra };
}

export const api = {
  health: () => request('GET', '/health'),

  auth: {
    login: (payload) => request('POST', '/auth/login', payload).then((data) => {
      saveAuth(data, payload.remember);
      return data;
    }),
    register: (payload) => request('POST', '/auth/register', payload).then((data) => {
      saveAuth(data, payload.remember);
      return data;
    }),
    me: () => request('GET', '/auth/me'),
    changePassword: (payload) => request('POST', '/auth/change-password', payload),
  },

  platform: {
    overview: (daysOrParams = {}) => request('GET', withQuery('/api/v1/helmet/platform/overview', overviewParams(daysOrParams))),
  },

  visitorEvidence: {
    list: (params = {}) => request('GET', withQuery('/api/v1/helmet/visitor-evidence', params)),
    create: (formData) => request('POST', '/api/v1/helmet/visitor-evidence', formData),
  },

  alerts: {
    list: (params = {}) => request('GET', withQuery('/api/v1/helmet/alerts', params)),
    get: (alertId) => request('GET', `/api/v1/helmet/alerts/${encodeURIComponent(alertId)}`),
    assign: (alertId, payload) => request('POST', `/api/v1/helmet/alerts/${encodeURIComponent(alertId)}/assign`, payload),
    status: (alertId, formData) => request('POST', `/api/v1/helmet/alerts/${encodeURIComponent(alertId)}/status`, formData),
  },

  people: {
    list: () => request('GET', '/api/v1/helmet/people'),
  },

  cameras: {
    list: () => request('GET', '/api/v1/helmet/cameras'),
    save: (payload) => request('POST', '/api/v1/helmet/cameras', payload),
    live: () => request('GET', '/api/v1/helmet/cameras/live'),
    browserInfer: (cameraId, formData) => request('POST', `/api/v1/helmet/cameras/${encodeURIComponent(cameraId)}/browser-infer`, formData),
  },

  reports: {
    summary: (daysOrParams = {}, extra = {}) => request('GET', withQuery('/api/v1/helmet/reports/summary', reportSummaryParams(daysOrParams, extra))),
    rows: (params = {}) => request('GET', withQuery('/api/v1/helmet/reports/rows', params)),
  },

  notifications: {
    list: () => request('GET', '/api/v1/helmet/notifications'),
    test: (payload) => request('POST', '/api/v1/helmet/notifications/test', payload),
  },

  hardCases: {
    list: (params = {}) => request('GET', withQuery('/api/v1/helmet/hard-cases', params)),
  },

  config: {
    summary: () => request('GET', '/api/v1/helmet/config/summary'),
  },

  accounts: {
    list: () => request('GET', '/api/v1/helmet/accounts'),
    save: (payload) => request('POST', '/api/v1/helmet/accounts', payload),
    remove: (username) => request('DELETE', `/api/v1/helmet/accounts/${encodeURIComponent(username)}`),
  },

  ops: {
    capabilities: () => request('GET', '/api/v1/helmet/ops/capabilities'),
    readiness: () => request('GET', '/api/v1/helmet/ops/readiness'),
    services: () => request('GET', '/api/v1/helmet/ops/services'),
    serviceAction: (serviceName, payload) => request('POST', `/api/v1/helmet/ops/services/${encodeURIComponent(serviceName)}/action`, payload),
    identitySummary: () => request('GET', '/api/v1/helmet/ops/identity/summary'),
    identitySync: (payload = {}) => request('POST', '/api/v1/helmet/ops/identity/sync', payload),
    identityBootstrap: (payload = {}) => request('POST', '/api/v1/helmet/ops/identity/bootstrap-defaults', payload),
    modelFeedback: () => request('GET', '/api/v1/helmet/ops/model-feedback'),
    qualitySummary: () => request('GET', '/api/v1/helmet/ops/quality-summary'),
    exportFeedback: (payload = {}) => request('POST', '/api/v1/helmet/ops/model-feedback/export', payload),
    buildFeedbackDataset: (payload = {}) => request('POST', '/api/v1/helmet/ops/model-feedback/dataset', payload),
    evidenceDelivery: () => request('GET', '/api/v1/helmet/ops/evidence-delivery'),
    validateStorage: (payload = {}) => request('POST', '/api/v1/helmet/ops/evidence-delivery/validate-storage', payload),
    validateNotification: (payload = {}) => request('POST', '/api/v1/helmet/ops/evidence-delivery/validate-notification', payload),
    backups: () => request('GET', '/api/v1/helmet/ops/backups'),
    createBackup: (payload = {}) => request('POST', '/api/v1/helmet/ops/backups', payload),
    restoreBackup: (payload) => request('POST', '/api/v1/helmet/ops/backups/restore', payload),
    releases: () => request('GET', '/api/v1/helmet/ops/releases'),
    createReleaseSnapshot: (payload = {}) => request('POST', '/api/v1/helmet/ops/releases/snapshot', payload),
    activateRelease: (payload) => request('POST', '/api/v1/helmet/ops/releases/activate', payload),
    rollbackRelease: (payload) => request('POST', '/api/v1/helmet/ops/releases/rollback', payload),
  },
};
