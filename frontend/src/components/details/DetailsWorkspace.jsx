import { useEffect, useMemo, useState } from "react";
import { FileField } from "@/components/shared/FileField";
import { buildApiUrl } from "@/lib/api";
import { saveBlobAsFile } from "@/lib/download";
import {
  deleteModelAsset,
  downloadModelArchive,
  fetchModels,
  selectActiveModel,
  uploadUserModel,
} from "@/lib/plantApi";

function describeHealth(health) {
  if (health.state === "online") {
    return "系统就绪";
  }
  if (health.state === "offline") {
    return "服务异常";
  }
  return "正在连接";
}

function describeModel(health) {
  if (health.state !== "online") {
    return "等待服务响应";
  }
  return health.data?.current_model || "尚未启用模型";
}

function describeOwner(item) {
  return item.owner_display_name || item.owner_username || (item.is_official ? "官方资源" : "当前用户");
}

export function DetailsWorkspace({ token, isAuthenticated, user, health }) {
  const isAdmin = user?.role === "admin";
  const [detailsView, setDetailsView] = useState("models");
  const [modelsState, setModelsState] = useState({
    loading: false,
    items: [],
    currentModel: "",
  });
  const [status, setStatus] = useState("模型资产已集中到这里。");
  const [error, setError] = useState("");
  const [busyKey, setBusyKey] = useState("");
  const [uploadForm, setUploadForm] = useState({
    modelFile: null,
    labelsFile: null,
    metadataFile: null,
    isPublic: false,
    activate: true,
  });

  useEffect(() => {
    if (!isAuthenticated || !token) {
      setModelsState({
        loading: false,
        items: [],
        currentModel: "",
      });
      return;
    }

    let cancelled = false;
    async function bootstrap() {
      setModelsState((current) => ({ ...current, loading: true }));
      setError("");
      try {
        const payload = await fetchModels(token);
        if (cancelled) {
          return;
        }
        setModelsState({
          loading: false,
          items: payload?.data?.available_model_items || [],
          currentModel: payload?.data?.current_model || "",
        });
        setStatus(payload?.message || "模型资产已加载。");
      } catch (nextError) {
        if (!cancelled) {
          setModelsState({
            loading: false,
            items: [],
            currentModel: "",
          });
          setError(nextError.message || "模型资产加载失败。");
        }
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, token]);

  const detailViews = useMemo(() => {
    const items = [
      {
        id: "models",
        label: "模型列表",
        summary: modelsState.currentModel || `${modelsState.items.length} 个可访问模型`,
      },
      {
        id: "upload",
        label: "上传模型",
        summary: isAdmin ? "上线或替换可用模型" : "上传个人模型",
      },
    ];
    if (isAdmin) {
      items.push({
        id: "deploy",
        label: "部署入口",
        summary: "接口文档与联调入口",
      });
    }
    return items;
  }, [isAdmin, modelsState.currentModel, modelsState.items.length]);
  const activeDetailsView = detailsView === "deploy" && !isAdmin ? "models" : detailsView;

  async function reloadModels(message = "") {
    if (!token) {
      return;
    }
    const payload = await fetchModels(token);
    setModelsState({
      loading: false,
      items: payload?.data?.available_model_items || [],
      currentModel: payload?.data?.current_model || "",
    });
    if (message) {
      setStatus(message);
    }
  }

  async function runAssetAction(key, action) {
    setBusyKey(key);
    setError("");
    try {
      await action();
    } catch (nextError) {
      setError(nextError.message || "模型资产操作失败。");
    } finally {
      setBusyKey("");
    }
  }

  async function handleModelUpload(event) {
    event.preventDefault();
    if (!uploadForm.modelFile) {
      setError("请先选择要上传的 ONNX 模型。");
      return;
    }
    await runAssetAction("upload-user-model", async () => {
      const payload = await uploadUserModel(token, uploadForm);
      setStatus(payload?.message || "个人模型已上传。");
      setUploadForm({
        modelFile: null,
        labelsFile: null,
        metadataFile: null,
        isPublic: false,
        activate: true,
      });
      await reloadModels(payload?.message || "模型资产已刷新。");
    });
  }

  return (
    <section className="native-workspace native-workspace--details">
      <div className="native-workspace__panel native-workspace__panel--controls">
        <div className="native-workspace__section-head">
          <p className="workspace__section-label">Assets</p>
          <h3>{isAdmin ? "模型资产与部署" : "模型资产"}</h3>
        </div>

        <div className="workspace-mode-switch" role="tablist" aria-label="资产工作区视图">
          {detailViews.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeDetailsView === item.id}
              className={`workspace-mode-switch__item${activeDetailsView === item.id ? " is-active" : ""}`}
              onClick={() => setDetailsView(item.id)}
            >
              <span>{item.label}</span>
              <strong>{item.summary}</strong>
            </button>
          ))}
        </div>

        <div className="native-inline-actions native-inline-actions--triple">
          <span className="native-pill native-pill--accent">{modelsState.currentModel || describeModel(health)}</span>
          <span className="native-pill native-pill--neutral">{describeHealth(health)}</span>
        </div>

        <div className="native-feedback">
          <p>{status}</p>
          {error ? <strong>{error}</strong> : null}
          {modelsState.loading ? <span>正在刷新模型资产...</span> : null}
        </div>
      </div>

      <div className="native-workspace__panel native-workspace__panel--canvas">
        <div className="native-workspace__section-head">
          <p className="workspace__section-label">
            {activeDetailsView === "models" ? "Model Assets" : activeDetailsView === "upload" ? "Upload" : "Deploy"}
          </p>
          <h3>
            {activeDetailsView === "models"
              ? (isAdmin ? "模型资产中心" : "个人模型中心")
              : activeDetailsView === "upload"
                ? (isAdmin ? "上传与替换模型" : "上传个人模型")
                : "部署入口"}
          </h3>
        </div>

        {!isAuthenticated ? (
          <div className="native-lock-panel">
            <strong>登录后管理模型资产</strong>
            <p>登录后会解锁模型上传、下载、删除和切换能力。</p>
          </div>
        ) : (
          <>
            {activeDetailsView === "upload" ? (
              <section className="asset-collection">
                <div className="asset-collection__head">
                  <div>
                    <p className="workspace__section-label">Upload</p>
                    <h3>{isAdmin ? "上传平台模型" : "上传个人模型"}</h3>
                  </div>
                  <span className="native-pill native-pill--neutral">
                    {uploadForm.activate ? "上传后启用" : "仅上传"}
                  </span>
                </div>
                <form className="native-form" onSubmit={handleModelUpload}>
                  <FileField
                    label="模型文件"
                    accept=".onnx"
                    file={uploadForm.modelFile}
                    onChange={(file) => setUploadForm((current) => ({ ...current, modelFile: file }))}
                    buttonLabel="选择 ONNX"
                  />
                  <FileField
                    label="标签文件"
                    accept=".json"
                    file={uploadForm.labelsFile}
                    onChange={(file) => setUploadForm((current) => ({ ...current, labelsFile: file }))}
                    buttonLabel="选择标签"
                  />
                  <FileField
                    label="说明文件"
                    accept=".json"
                    file={uploadForm.metadataFile}
                    onChange={(file) => setUploadForm((current) => ({ ...current, metadataFile: file }))}
                    buttonLabel="选择说明"
                  />
                  <label className="native-checkbox">
                    <input
                      type="checkbox"
                      checked={uploadForm.isPublic}
                      onChange={(event) => setUploadForm((current) => ({ ...current, isPublic: event.target.checked }))}
                    />
                    <span>上传为公开模型</span>
                  </label>
                  <label className="native-checkbox">
                    <input
                      type="checkbox"
                      checked={uploadForm.activate}
                      onChange={(event) => setUploadForm((current) => ({ ...current, activate: event.target.checked }))}
                    />
                    <span>上传后立即使用</span>
                  </label>
                  <button type="submit" className="primary" disabled={busyKey === "upload-user-model"}>
                    {busyKey === "upload-user-model" ? "上传中..." : "上传模型"}
                  </button>
                </form>
              </section>
            ) : null}

            {activeDetailsView === "models" ? (
              <section className="asset-collection asset-collection--wide">
                <div className="asset-collection__head">
                  <div>
                    <p className="workspace__section-label">Models</p>
                    <h3>可访问模型</h3>
                  </div>
                  <span className="native-pill native-pill--accent">{modelsState.currentModel || "未启用"}</span>
                </div>
                {!modelsState.items.length ? (
                  <div className="native-empty native-empty--compact">
                    <p>当前账号还没有可访问模型。</p>
                  </div>
                ) : (
                  <div className="asset-list">
                    {modelsState.items.map((model) => (
                      <article key={model.name} className={`asset-row${model.is_active ? " is-active" : ""}`}>
                        <div className="asset-row__main">
                          <div className="asset-row__title">
                            <strong>{model.name}</strong>
                            <div className="asset-row__badges">
                              {model.is_active ? <span className="native-pill native-pill--accent">当前模型</span> : null}
                              <span className="native-pill native-pill--neutral">{model.is_public ? "公开" : "私有"}</span>
                              {model.is_official ? <span className="native-pill native-pill--warm">官方</span> : null}
                            </div>
                          </div>
                          <p>{describeOwner(model)}</p>
                        </div>
                        <div className="asset-row__actions">
                          <button
                            type="button"
                            className="secondary native-utility-button"
                            disabled={busyKey === `download-user-model-${model.name}`}
                            onClick={() => runAssetAction(`download-user-model-${model.name}`, async () => {
                              const blob = await downloadModelArchive(token, model.name);
                              saveBlobAsFile(blob, `${model.name.replace(/\.onnx$/i, "")}_model.zip`);
                              setStatus(`模型 ${model.name} 已开始下载。`);
                            })}
                          >
                            下载
                          </button>
                          {user?.role === "admin" ? (
                            <button
                              type="button"
                              className="secondary native-utility-button"
                              disabled={busyKey === `activate-user-model-${model.name}` || model.is_active}
                              onClick={() => runAssetAction(`activate-user-model-${model.name}`, async () => {
                                const payload = await selectActiveModel(token, model.name);
                                await reloadModels(payload?.message || `已切换模型 ${model.name}。`);
                              })}
                            >
                              {model.is_active ? "正在使用" : "设为当前"}
                            </button>
                          ) : null}
                          {model.can_manage ? (
                            <button
                              type="button"
                              className="secondary native-utility-button"
                              disabled={busyKey === `delete-user-model-${model.name}`}
                              onClick={() => {
                                if (!window.confirm(`确定删除模型 ${model.name} 吗？`)) {
                                  return;
                                }
                                runAssetAction(`delete-user-model-${model.name}`, async () => {
                                  const payload = await deleteModelAsset(token, model.name);
                                  await reloadModels(payload?.message || `模型 ${model.name} 已删除。`);
                                });
                              }}
                            >
                              删除
                            </button>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            ) : null}

            {activeDetailsView === "deploy" && isAdmin ? (
              <section className="asset-collection asset-collection--wide">
                <div className="asset-collection__head">
                  <div>
                    <p className="workspace__section-label">Deploy</p>
                    <h3>部署与联调入口</h3>
                  </div>
                </div>
                <div className="guide-grid">
                  <article className="guide-card">
                    <span>接口文档</span>
                    <strong>FastAPI Docs</strong>
                    <p>部署后可直接用它验证接口是否在线。</p>
                    <a className="native-link" href={buildApiUrl("/docs")} target="_blank" rel="noreferrer">
                      打开接口文档
                    </a>
                  </article>
                  <article className="guide-card">
                    <span>OpenAPI</span>
                    <strong>Schema JSON</strong>
                    <p>前后端联调时可直接下载最新 schema。</p>
                    <a className="native-link" href={buildApiUrl("/openapi.json")} target="_blank" rel="noreferrer">
                      打开 Schema
                    </a>
                  </article>
                  <article className="guide-card">
                    <span>当前发布</span>
                    <strong>{modelsState.currentModel || describeModel(health)}</strong>
                    <p>发布前确认当前在线模型名称和接口基址，避免切错版本。</p>
                  </article>
                </div>
              </section>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
