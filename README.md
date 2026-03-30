> 当前主运行栈
> - 前端：`frontend/`
> - Spring 主后端：`backend-spring/`
> - Python legacy 能力层：`plantbackend/`
> - Docker 部署：`deploy/`
>
> 根目录原有 `src/` 与 `pom.xml` 为早期实验代码，已保留但不参与当前 Docker / 前后端主链路。
# Plant

植物病害智能识别与训练平台。

当前仓库已经重构为前后端分离架构：

- `frontend/`：React + Vite 前端
- `backend-spring/`：对外主后端，基于 Spring Boot
- `plantbackend/`：保留的 Python legacy 能力层，继续承载推理、训练、标注数据处理、AI 建议等已有能力

这次架构调整的目标是“重构而不改功能”。因此，前端访问入口和主要接口协议保持不变，但对外服务入口已经切换为 Spring。

## 项目结构

```text
plant/
├─ frontend/                  # Vite + React 前端
│  ├─ src/                    # 页面组件、hooks、API 客户端、样式
│  ├─ public/
│  ├─ tests/
│  └─ vite.config.js
├─ backend-spring/            # Spring Boot 主后端
│  ├─ src/main/java/
│  ├─ src/main/resources/
│  └─ pom.xml
├─ plantbackend/              # Python legacy 能力层
│  ├─ api_router.py
│  ├─ auth_store.py
│  ├─ model_service.py
│  ├─ ai_advice_service.py
│  ├─ train_yolo.py
│  ├─ augment_yolo.py
│  └─ .env.example
├─ deploy/                    # Docker / Nginx / Compose 部署文件
├─ tools/
├─ start_backend.ps1          # 启动 Spring 主后端
├─ start_legacy_backend.ps1   # 单独启动 Python legacy 后端
├─ start_frontend.ps1         # 启动前端开发服务器
└─ Makefile
```

## 当前架构

### 运行关系

默认本地开发时有三层：

1. `frontend` 运行在 `5500`
2. `backend-spring` 运行在 `7800`
3. `plantbackend` legacy 后端运行在 `7801`

前端只请求 Spring 主后端；Spring 再将原有业务接口转发给 Python legacy 后端。这样做的好处是：

- 前端不需要大改
- 现有功能可以继续使用
- Java 后端可以逐步接管旧能力，而不是一次性重写所有推理和训练逻辑

### 当前职责划分

- `frontend/`：界面、工作台、会话管理、前端 API 调用
- `backend-spring/`：统一入口、网关代理、后续 Java 化承接点
- `plantbackend/`：模型推理、训练任务、标注数据管理、AI 建议、已有认证与资源访问逻辑

## 环境要求

推荐准备以下环境：

- Java 21 或更高版本
- Maven 3.9+
- Node.js 20+
- Python 3.10+（如果要训练，推荐单独准备 Python 3.12 环境）

如果你希望 Spring 自动拉起 legacy 后端，需要保证 Python 环境中已安装 `uvicorn` 和 `plantbackend/requirements.txt` 里的依赖。

## 快速启动

### Windows / PowerShell

推荐直接使用仓库里的启动脚本。

先启动主后端：

```powershell
./start_backend.ps1
```

再启动前端：

```powershell
./start_frontend.ps1
```

默认访问地址：

- 前端：`http://127.0.0.1:5500`
- Spring 主后端：`http://127.0.0.1:7800`
- 健康检查：`http://127.0.0.1:7800/health`

`start_backend.ps1` 会先构建 `backend-spring`，再以 `java -jar` 方式启动它。默认情况下，Spring 会尝试把 Python legacy 后端拉到 `7801`。

如果本机没有全局 Python，但你已经有一个可用的虚拟环境，也可以显式指定：
```powershell
./start_backend.ps1 -LegacyPythonPath D:\path\to\python.exe
```

单独启动 legacy 后端时也支持：
```powershell
./start_legacy_backend.ps1 -PythonPath D:\path\to\python.exe -Port 7801
```

### 如果 legacy 后端没有自动启动

如果当前机器还没准备好 Python 环境，可以手动启动 legacy 后端：

```powershell
./start_legacy_backend.ps1 -Port 7801
```

然后再启动：

```powershell
./start_backend.ps1
```

## Python legacy 环境准备

从示例环境文件开始：

```bash
cp plantbackend/.env.example plantbackend/.env
```

至少要设置管理员密码：

```bash
export BOOTSTRAP_ADMIN_PASSWORD="请改成你自己的强密码"
```

### 仅运行 legacy API

```bash
cd plantbackend
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m uvicorn asgi:app --host 127.0.0.1 --port 7801
```

### 需要训练能力时

如果本机默认 Python 版本对 `torch` / `ultralytics` 不兼容，建议准备单独的训练环境：

```bash
cd plantbackend
python3.12 -m venv .venv-train
. .venv-train/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

训练相关脚本会优先尝试使用训练环境解释器。

## 前端开发

```bash
cd frontend
npm install
npm run dev
```

开发代理默认转发到：

- `/api/*` -> `http://127.0.0.1:7800/*`

如果你想改开发代理目标，可以设置：

```bash
VITE_DEV_API_PROXY_TARGET=http://127.0.0.1:7800
```

## Docker 首次启动说明

- 首次启动时，`legacy-backend` 容器会自动把镜像内自带的默认模型写入 `models` 卷，因此即使不挂载宿主机目录，也会有一个可用的 `best.onnx`。
- 鉴权数据库已改为运行时目录：`/app/plantbackend/runtime/plant_auth.db`。
- 首次启动必须设置管理员密码，当前示例文件在 `deploy/backend.env` 里使用 `BOOTSTRAP_ADMIN_PASSWORD=change_me`，实际使用前请修改。
- `backend-spring` 容器镜像内已包含 `plantbackend/augment_yolo.py` 和 `augmentation_algorithms/`，不再依赖整目录 bind mount。
## Docker 部署

部署配置位于 `deploy/`。

```bash
cd deploy
cp backend.env.example backend.env
docker compose -f compose.prod.yml up --build
```

Compose 当前会启动：

- `legacy-backend`：Python 后端
- `backend`：Spring 主后端
- `frontend`：Nginx 托管的前端静态站点

对外访问端口：

- `5500`：前端
- `7800`：Spring 主后端

## 常用命令

根目录 `Makefile` 中保留了常用命令：

```bash
make backend
make frontend
make clean
make docker-up
```

说明：

- `make backend`：构建并启动 Spring 主后端
- `make frontend`：启动前端开发环境
- `make clean`：执行工作区清理脚本
- `make docker-up`：启动生产部署编排

## 关键环境变量

### Spring 主后端

- `SPRING_SERVER_PORT`
- `LEGACY_BACKEND_BASE_URL`
- `LEGACY_BACKEND_AUTO_START`
- `LEGACY_BACKEND_PORT`
- `LEGACY_BACKEND_WORKING_DIRECTORY`
- `LEGACY_BACKEND_PYTHON_PATH`

### Python legacy 后端

可参考 `plantbackend/.env.example`：

- `BOOTSTRAP_ADMIN_PASSWORD`
- `ALLOWED_ORIGINS`
- `MODELS_DIR`
- `AUTH_DB_PATH`
- `ANNOTATION_DATASETS_ROOT`
- `TRAINING_RUNS_DIR`
- `TRAINING_BASE_MODEL`
- `TRAINING_EPOCHS`
- `TRAINING_IMGSZ`

### AI 建议与大模型接入

- `AI_API_URL`
- `AI_API_BASE_URL`
- `AI_API_CHAT_PATH`
- `AI_API_KEY`
- `AI_API_MODEL`
- `AI_API_TIMEOUT`
- `AI_API_MAX_IMAGE_BYTES`
- `AI_API_IMAGE_DETAIL`

如果配置了兼容 OpenAI 的模型服务，系统会优先调用远端多模态或文本模型生成建议；未配置时会退回本地内置建议。

## 运行数据说明

以下内容属于运行数据，不建议当作“无用文件”直接删除：

- `plantbackend/models/`
- `plantbackend/annotation_datasets/`
- `plantbackend/training_runs/`
- `plantbackend/plant_auth.db`
- 上传后的模型标签和元数据文件

## 当前阶段说明

当前版本已经完成“以 Spring 为基础的前后端分离重构”，但还没有把所有业务实现彻底改写成纯 Java。现阶段的真实状态是：

- Spring 是主后端入口
- Python legacy 层仍然承接原有核心能力
- 前端接口保持兼容

如果后续继续推进，可以再按模块逐步把认证、模型管理、标注、训练任务等能力从 Python 迁移到 Java。


