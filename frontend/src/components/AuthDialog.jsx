import { useEffect, useState } from "react";
import { BrandMark } from "./BrandMark";

const INITIAL_FORM = {
  username: "",
  password: "",
  displayName: "",
};

export function AuthDialog({ open, mode, loading = false, error = "", onClose, onModeChange, onLogin, onRegister }) {
  const [form, setForm] = useState(INITIAL_FORM);

  useEffect(() => {
    if (open) {
      setForm(INITIAL_FORM);
    }
  }, [open, mode]);

  if (!open) {
    return null;
  }

  const isRegister = mode === "register";

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (isRegister) {
      await onRegister(form);
      return;
    }
    await onLogin(form);
  };

  return (
    <div className="auth-dialog" role="dialog" aria-modal="true" aria-label="登录与注册">
      <div className="auth-dialog__backdrop" onClick={onClose} />
      <div className="auth-dialog__panel">
        <div className="auth-dialog__hero">
          <div className="auth-dialog__hero-top">
            <BrandMark />
            <span className="auth-dialog__hero-badge">Encrypted Session</span>
          </div>
          <div className="auth-dialog__hero-copy">
            <h2>进入工作台</h2>
            <p>登录后直接回到当前模块，浏览器只保存加密后的会话凭证。</p>
          </div>
        </div>
        <div className="auth-dialog__form-wrap">
          <div className="auth-tabs" role="tablist" aria-label="登录注册切换">
            <button type="button" className={`auth-tabs__tab${!isRegister ? " is-active" : ""}`} onClick={() => onModeChange("login")}>
              登录
            </button>
            <button type="button" className={`auth-tabs__tab${isRegister ? " is-active" : ""}`} onClick={() => onModeChange("register")}>
              注册
            </button>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {isRegister ? (
              <label className="field">
                <span>显示名称</span>
                <input
                  value={form.displayName}
                  onChange={(event) => setForm((current) => ({ ...current, displayName: event.target.value }))}
                  placeholder="例如 张三"
                  autoComplete="nickname"
                />
              </label>
            ) : null}
            <label className="field">
              <span>用户名</span>
              <input
                value={form.username}
                onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
                placeholder="请输入用户名"
                autoComplete="username"
              />
            </label>
            <label className="field">
              <span>密码</span>
              <input
                type="password"
                value={form.password}
                onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                placeholder="请输入密码"
                autoComplete={isRegister ? "new-password" : "current-password"}
              />
            </label>
            {error ? <p className="auth-form__error">{error}</p> : null}
            <div className="auth-form__actions">
              <button type="submit" className="primary" disabled={loading}>
                {loading ? "处理中..." : isRegister ? "注册并进入" : "登录并进入"}
              </button>
              <button type="button" className="secondary" onClick={onClose}>
                关闭
              </button>
            </div>
            <p className="auth-form__privacy">浏览器端仅保存加密后的会话凭证，密码不会被前端缓存。</p>
          </form>
        </div>
      </div>
    </div>
  );
}
