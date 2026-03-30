import { useEffect, useState } from "react";
import { AdminWorkspace } from "@/components/admin/AdminWorkspace";
import { BrandMark } from "@/components/BrandMark";
import { AnnotationWorkspace } from "@/components/annotation/AnnotationWorkspace";
import { AuthDialog } from "@/components/AuthDialog";
import { DetailsWorkspace } from "@/components/details/DetailsWorkspace";
import { RecognitionWorkspace } from "@/components/recognition/RecognitionWorkspace";
import { WorkspaceNav } from "@/components/WorkspaceNav";
import {
  DEFAULT_WORKSPACE,
  WORKSPACES,
  getWorkspaceMeta,
} from "@/appConfig";
import { requestApi } from "@/lib/api";
import { useSession } from "@/hooks/useSession";

const INITIAL_HEALTH = {
  state: "checking",
  message: "正在检查服务",
  data: null,
};

function getHealthSummary(health) {
  if (health.state === "online") {
    return "系统就绪";
  }
  if (health.state === "offline") {
    return "服务异常";
  }
  return "正在连接";
}

function App() {
  const session = useSession();
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState("login");
  const [hasPromptedAuth, setHasPromptedAuth] = useState(false);
  const [health, setHealth] = useState(INITIAL_HEALTH);
  const [recognitionPayload, setRecognitionPayload] = useState(null);
  const [workspace, setWorkspace] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return getWorkspaceMeta(params.get("workspace") || DEFAULT_WORKSPACE).id;
  });

  useEffect(() => {
    if (!session.isAuthenticated) {
      return;
    }
    if (session.user?.role !== "admin" && workspace === "admin") {
      setWorkspace(DEFAULT_WORKSPACE);
    }
  }, [session.isAuthenticated, session.user, workspace]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("workspace", workspace);
    const nextSearch = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}?${nextSearch}`);
  }, [workspace]);

  useEffect(() => {
    let cancelled = false;
    let activeController = null;

    async function loadHealth() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        const payload = await requestApi("/health", {
          token: session.token,
          signal: controller.signal,
        });
        if (cancelled || controller.signal.aborted) {
          return;
        }
        setHealth({
          state: "online",
          message: payload?.message || "服务可用",
          data: payload?.data || null,
        });
      } catch (error) {
        if (cancelled || controller.signal.aborted) {
          return;
        }
        setHealth({
          state: "offline",
          message: error.message || "服务不可用",
          data: null,
        });
      }
    }

    loadHealth();
    const timer = window.setInterval(loadHealth, 15000);
    return () => {
      cancelled = true;
      activeController?.abort();
      window.clearInterval(timer);
    };
  }, [session.token]);

  useEffect(() => {
    if (session.isAuthenticated) {
      setHasPromptedAuth(false);
      return;
    }
    if (!session.isReady || hasPromptedAuth) {
      return;
    }
    setAuthMode("login");
    setAuthOpen(true);
    setHasPromptedAuth(true);
  }, [hasPromptedAuth, session.isAuthenticated, session.isReady]);

  const activeWorkspace = session.user?.role === "admin" || workspace !== "admin"
    ? workspace
    : DEFAULT_WORKSPACE;
  const isAuthenticated = session.isAuthenticated;
  const canShowAdmin = session.user?.role === "admin";
  const workspaceMeta = getWorkspaceMeta(activeWorkspace);
  const visibleWorkspaces = WORKSPACES.filter((item) => canShowAdmin || item.id !== "admin");
  const healthSummary = getHealthSummary(health);
  const securitySummary = isAuthenticated
    ? "加密会话"
    : "加密存储";

  function openAuth(nextMode = "login") {
    setAuthMode(nextMode);
    setAuthOpen(true);
  }

  function handleWorkspaceChange(nextWorkspace) {
    const nextMeta = getWorkspaceMeta(nextWorkspace);
    if (!isAuthenticated) {
      setWorkspace(nextMeta.id);
      openAuth("login");
      return;
    }
    if (!canShowAdmin && nextMeta.id === "admin") {
      return;
    }
    setWorkspace(nextMeta.id);
  }

  function renderWorkspaceSurface() {
    if (activeWorkspace === "recognition") {
      return (
        <RecognitionWorkspace
          token={session.token}
          isAuthenticated={isAuthenticated}
          initialPayload={recognitionPayload}
          onPredictionReady={setRecognitionPayload}
          onOpenAnnotation={() => setWorkspace("annotation")}
        />
      );
    }

    if (activeWorkspace === "annotation") {
      return (
        <AnnotationWorkspace
          token={session.token}
          isAuthenticated={isAuthenticated}
          recognitionPayload={recognitionPayload}
        />
      );
    }

    if (activeWorkspace === "details") {
      return (
        <DetailsWorkspace
          token={session.token}
          isAuthenticated={isAuthenticated}
          user={session.user}
          health={health}
        />
      );
    }

    return (
      <AdminWorkspace
        token={session.token}
        isAuthenticated={isAuthenticated}
        user={session.user}
      />
    );
  }

  function renderGuestLanding() {
    return (
      <main className="landing">
        <section className="landing__hero">
          <div className="landing__copy landing__copy--compact">
            <div className="landing__badge-row">
              <p className="eyebrow">Plant Disease Field Console</p>
              <span className="landing__stamp">Encrypted Session</span>
            </div>
            <h1>登录后直接进入工作台</h1>
            <p className="landing__lead">
              识别、标注训练和模型资产都在同一站点完成，本地会话凭证只以加密形式保存在浏览器中。
            </p>

            <div className="landing__actions">
              <button type="button" className="primary" onClick={() => openAuth("login")}>
                立即登录
              </button>
              <button type="button" className="secondary" onClick={() => openAuth("register")}>
                注册账号
              </button>
            </div>

            <div className="landing__trust" aria-label="登录状态">
              <span>{healthSummary}</span>
              <span>{securitySummary}</span>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
      <div className="app-shell">
      {!isAuthenticated ? (
        <header className="topbar">
          <BrandMark compact />
          <div className="topbar__actions">
            <button type="button" className="secondary" onClick={() => openAuth("login")}>
              登录
            </button>
            <button type="button" className="primary" onClick={() => openAuth("register")}>
              注册
            </button>
          </div>
        </header>
      ) : null}

      {isAuthenticated ? (
        <div className="console-shell console-shell--sidebar">
          <aside className="console-rail">
            <div className="console-rail__brand">
              <BrandMark compact />
            </div>

            <div className="console-rail__workspace">
              <span>{workspaceMeta.groupLabel || "Workspace"} / {workspaceMeta.step || "--"}</span>
              <strong>{workspaceMeta.label}</strong>
              <p>{workspaceMeta.hint || workspaceMeta.focusTitle || workspaceMeta.summary}</p>
              <div className="console-rail__badges" aria-label="会话状态">
                <span className="console-rail__badge">{healthSummary}</span>
                <span className="console-rail__badge">{securitySummary}</span>
              </div>
            </div>

            <WorkspaceNav
              items={visibleWorkspaces}
              activeWorkspace={activeWorkspace}
              onChangeWorkspace={handleWorkspaceChange}
              canShowAdmin={canShowAdmin}
              layout="rail"
            />

            <div className="console-rail__session">
              <div className="topbar__user">
                <strong>{session.user?.display_name || session.user?.username || "已登录"}</strong>
                <span>{session.user?.role === "admin" ? "管理员" : "普通用户"}</span>
              </div>
              <button
                type="button"
                className="secondary"
                onClick={async () => {
                  await session.logout();
                  setWorkspace(DEFAULT_WORKSPACE);
                }}
              >
                退出登录
              </button>
            </div>
          </aside>

          <main className="workspace__main workspace__main--full console-stage">
            <section className="workspace__canvas-shell workspace__canvas-shell--full">
              {renderWorkspaceSurface()}
            </section>
          </main>
        </div>
      ) : renderGuestLanding()}

      <AuthDialog
        open={authOpen}
        mode={authMode}
        loading={session.status === "authenticating"}
        error={session.error}
        onClose={() => setAuthOpen(false)}
        onModeChange={setAuthMode}
        onLogin={async ({ username, password }) => {
          await session.login({ username, password });
          setAuthOpen(false);
        }}
        onRegister={async ({ username, password, displayName }) => {
          await session.register({
            username,
            password,
            display_name: displayName,
          });
          setAuthOpen(false);
        }}
      />
    </div>
  );
}

export default App;
