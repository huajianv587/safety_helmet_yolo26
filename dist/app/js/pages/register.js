import { api } from '../api.js?v=1';
import { pick, t } from '../i18n.js?v=1';
import { escapeHtml } from '../utils.js?v=1';
import { toast } from '../components/toast.js?v=1';

export async function render(container) {
  container.innerHTML = `
    <section class="auth-panel" data-page-ready="register">
      <div class="auth-mark">SH</div>
      <div class="auth-title">${pick('注册安全帽指挥台账号', 'Register Command Center Account')}</div>
      <div class="auth-copy">${pick('当前按本地受控环境策略开放注册。注册成功后默认拥有完整配置、复核、通知和账号管理权限。', 'Registration is open for the local controlled environment. New accounts receive full configuration, review, notification, and account administration access.')}</div>
      <form id="register-form" class="form-grid one">
        <label class="form-row">
          <span class="form-label">${t('auth.username')}</span>
          <input class="form-input" id="register-username" type="email" autocomplete="username" required placeholder="operator@example.test">
        </label>
        <label class="form-row">
          <span class="form-label">${pick('显示名称', 'Display name')}</span>
          <input class="form-input" id="register-display" autocomplete="name" placeholder="${pick('现场管理员', 'Site Administrator')}">
        </label>
        <label class="form-row">
          <span class="form-label">${pick('邮箱', 'Email')}</span>
          <input class="form-input" id="register-email" type="email" autocomplete="email" placeholder="operator@example.test">
        </label>
        <label class="form-row">
          <span class="form-label">${t('auth.password')}</span>
          <input class="form-input" id="register-password" type="password" autocomplete="new-password" required minlength="8">
        </label>
        <label class="form-row">
          <span class="form-label">${pick('确认密码', 'Confirm password')}</span>
          <input class="form-input" id="register-confirm" type="password" autocomplete="new-password" required minlength="8">
        </label>
        <label class="form-row">
          <span><input id="register-remember" type="checkbox" checked> ${t('auth.remember')}</span>
        </label>
        <div class="guard-note">${pick('安全提示：公开注册默认 admin 仅适合本机或受控网络。上线前请关闭公开注册或接入外部身份源。', 'Security note: public admin registration is suitable only for local or controlled networks. Disable it or use an external identity provider before public deployment.')}</div>
        <div class="auth-actions">
          <button class="btn btn-primary" id="register-btn" type="submit">${t('auth.register')}</button>
          <a class="btn btn-ghost" href="#/login">${t('auth.login')}</a>
          <a class="btn btn-ghost" href="#/dashboard">${pick('继续访客浏览', 'Continue as guest')}</a>
        </div>
      </form>
    </section>`;

  container.querySelector('#register-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const password = container.querySelector('#register-password').value;
    const confirm = container.querySelector('#register-confirm').value;
    if (password !== confirm) {
      toast.warning(pick('密码不一致', 'Password mismatch'), pick('请确认两次输入的新密码一致。', 'Please confirm both password fields match.'));
      return;
    }
    const button = container.querySelector('#register-btn');
    const original = button.textContent;
    button.disabled = true;
    button.textContent = pick('正在注册', 'Registering');
    try {
      const username = container.querySelector('#register-username').value;
      const email = container.querySelector('#register-email').value || username;
      const response = await api.auth.register({
        username,
        email,
        password,
        display_name: container.querySelector('#register-display').value,
        remember: container.querySelector('#register-remember').checked,
      });
      toast.success(pick('注册成功', 'Registration complete'), escapeHtml(response.user.display_name || response.user.username));
      window.location.hash = '#/dashboard';
    } catch (error) {
      toast.error(pick('注册失败', 'Registration failed'), error.message);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  });
}
