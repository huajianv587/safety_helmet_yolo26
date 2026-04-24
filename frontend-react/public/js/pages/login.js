import { api } from '../api.js?v=1';
import { pick, t } from '../i18n.js?v=1';
import { escapeHtml } from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

export async function render(container) {
  container.innerHTML = `
    <section class="auth-panel" data-page-ready="login">
      <div class="auth-mark">SH</div>
      <div class="auth-title">${t('auth.welcome')}</div>
      <div class="auth-copy">${pick('不登录也可以浏览功能页。登录或注册后可以修改配置、处置工单、发送测试通知和管理账号。', 'You can browse without signing in. Login or register to change configuration, resolve cases, test notifications, and manage accounts.')}</div>
      <form id="login-form" class="form-grid one">
        <label class="form-row">
          <span class="form-label">${t('auth.username')}</span>
          <input class="form-input" id="username" autocomplete="username" required>
        </label>
        <label class="form-row">
          <span class="form-label">${t('auth.password')}</span>
          <input class="form-input" id="password" type="password" autocomplete="current-password" required>
        </label>
        <label class="form-row">
          <span><input id="remember" type="checkbox"> ${t('auth.remember')}</span>
        </label>
        <div class="auth-actions">
          <button class="btn btn-primary" id="login-btn" type="submit">${t('auth.login')}</button>
          <a class="btn btn-ghost" href="#/register">${t('auth.register')}</a>
          <a class="btn btn-ghost" href="#/dashboard">${pick('继续访客浏览', 'Continue as guest')}</a>
        </div>
      </form>
    </section>`;

  container.querySelector('#login-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = container.querySelector('#login-btn');
    const original = button.textContent;
    button.disabled = true;
    button.textContent = pick('正在登录', 'Signing in');
    try {
      const response = await api.auth.login({
        username: container.querySelector('#username').value,
        password: container.querySelector('#password').value,
        remember: container.querySelector('#remember').checked,
      });
      toast.success(t('auth.welcome'), escapeHtml(response.user.display_name || response.user.username));
      window.location.hash = '#/dashboard';
    } catch (error) {
      toast.error(pick('登录失败', 'Login failed'), error.message);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  });
}
