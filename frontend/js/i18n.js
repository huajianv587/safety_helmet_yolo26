const DICT = {
  zh: {
    'nav.platform': '现场态势',
    'nav.ops': '闭环处置',
    'nav.config': '运行配置',
    'nav.operations': '运维工作台',
    'page.login': '登录配置',
    'page.register': '注册账号',
    'page.dashboard': '总览',
    'page.review': '复核台',
    'page.cameras': '摄像头现场',
    'page.reports': '报表',
    'page.hard_cases': '回流池',
    'page.config': '配置中心',
    'page.operations': '运维工作台',
    'page.notifications': '通知中心',
    'page.access_admin': '账号管理',
    'auth.login': '登录',
    'auth.register': '注册账号',
    'auth.logout': '退出',
    'auth.username': '账号',
    'auth.password': '密码',
    'auth.remember': '保持登录',
    'auth.welcome': '欢迎回来',
    'auth.guest': '访客模式',
    'auth.login_to_configure': '登录后可配置',
    'auth.change_password': '修改密码',
    'common.loading': '正在加载',
    'common.empty': '暂无数据',
    'common.refresh': '刷新',
    'common.save': '保存',
    'common.export': '导出',
    'common.retry': '重试',
    'common.cancel': '取消',
    'common.confirm': '确认',
    'common.backend_online': '后端在线',
    'common.backend_offline': '后端离线',
    'common.connecting': '连接中',
    'common.display_controls': '显示控制',
    'common.toggle_theme': '切换明暗主题',
    'common.page_load_failed': '页面加载失败',
  },
  en: {
    'nav.platform': 'Field Posture',
    'nav.ops': 'Closed Loop',
    'nav.config': 'Runtime Config',
    'nav.operations': 'Operations Studio',
    'page.login': 'Login',
    'page.register': 'Register',
    'page.dashboard': 'Dashboard',
    'page.review': 'Review Desk',
    'page.cameras': 'Live Cameras',
    'page.reports': 'Reports',
    'page.hard_cases': 'Hard Cases',
    'page.config': 'Config Center',
    'page.operations': 'Operations Studio',
    'page.notifications': 'Notifications',
    'page.access_admin': 'Access Admin',
    'auth.login': 'Login',
    'auth.register': 'Register',
    'auth.logout': 'Logout',
    'auth.username': 'Username',
    'auth.password': 'Password',
    'auth.remember': 'Keep me signed in',
    'auth.welcome': 'Welcome back',
    'auth.guest': 'Guest mode',
    'auth.login_to_configure': 'Login to configure',
    'auth.change_password': 'Change password',
    'common.loading': 'Loading',
    'common.empty': 'No data yet',
    'common.refresh': 'Refresh',
    'common.save': 'Save',
    'common.export': 'Export',
    'common.retry': 'Retry',
    'common.cancel': 'Cancel',
    'common.confirm': 'Confirm',
    'common.backend_online': 'Backend online',
    'common.backend_offline': 'Backend offline',
    'common.connecting': 'Connecting',
    'common.display_controls': 'Display controls',
    'common.toggle_theme': 'Toggle theme',
    'common.page_load_failed': 'Page load failed',
  },
};

let lang = localStorage.getItem('helmet-lang') === 'en' ? 'en' : 'zh';
const listeners = new Set();

function syncDocumentLang() {
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
}

export function getLang() {
  return lang;
}

export function setLang(next) {
  lang = next === 'en' ? 'en' : 'zh';
  localStorage.setItem('helmet-lang', lang);
  syncDocumentLang();
  listeners.forEach((listener) => listener(lang));
}

export function onLangChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function t(key) {
  return DICT[lang]?.[key] || DICT.en[key] || key;
}

export function zh() {
  return lang === 'zh';
}

export function pick(zhText, enText) {
  return zh() ? zhText : enText;
}

syncDocumentLang();
