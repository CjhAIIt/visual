# Plant

Plant 是一个植物病害识别、标注与训练平台，当前仓库采用前后端分层架构。

当前实际在用的主链路只有三层：

- `frontend/`：React + Vite 工作台前端
- `backend-spring/`：Spring Boot 对外主后端与网关
- `plantbackend/`：Python legacy 能力层，负责推理、训练、数据集导入和 AI 建议

根目录早期的 Spring 初始化工程已经移除，仓库根目录现在只保留启动脚本、部署文件和共享工具脚本。

## 架构说明

### 本地开发

1. 前端运行在 `http://127.0.0.1:5500`
2. Spring 后端运行在 `http://127.0.0.1:7800`
3. Python legacy 后端运行在 `http://127.0.0.1:7801`

前端只请求 Spring。Spring 负责对外 API、统一入口和兼容层，推理/训练等现有能力仍由 Python 层承接。

### Docker 部署

- `frontend`：Nginx 托管的静态前端
- `backend`：Spring 主后端
- `legacy-backend`：Python legacy 后端

在 Docker Compose 中，Spring 通过 `http://legacy-backend:7800` 调用 legacy 服务。

## 仓库结构

```text
.
|-- frontend/                 # React + Vite 前端
|-- backend-spring/           # 当前唯一生效的 Spring Boot 后端
|-- plantbackend/             # Python legacy 后端与训练链路
|-- deploy/                   # Dockerfile、Compose、部署配置
|-- tools/                    # 冒烟检查、打包、清理脚本
|-- output/demo/              # 可选演示素材
|-- start_backend.ps1         # 构建并启动 Spring，可自动拉起 legacy
|-- start_frontend.ps1        # 安装依赖并启动 Vite
|-- start_legacy_backend.ps1  # 单独启动 legacy 后端
|-- serve_frontend.py         # 构建产物的简易静态服务脚本
`-- Makefile                  # 常用命令入口
```

## 环境要求

- Java 21+
- Maven 3.9+
- Node.js 20+
- Python 3.10+

如果要跑训练链路，仍建议单独准备 Python 3.12 环境。

## 快速启动

### 推荐方式：Windows / PowerShell

在仓库根目录执行：

```powershell
./start_backend.ps1
./start_frontend.ps1
```

启动完成后：

- 前端：`http://127.0.0.1:5500`
- Spring 后端：`http://127.0.0.1:7800`
- 健康检查：`http://127.0.0.1:7800/health`

`start_backend.ps1` 会先构建 `backend-spring/`，再启动最新的可运行 jar；如果 legacy 后端未启动，Spring 会尝试自动拉起它。

如果你希望 Spring 使用指定的 Python 解释器来启动 legacy：

```powershell
./start_backend.ps1 -LegacyPythonPath D:\path\to\python.exe
```

如果自动拉起不可用，可以先手动把 legacy 跑在 `7801`，再启动 Spring：

```powershell
./start_legacy_backend.ps1 -PythonPath D:\path\to\python.exe -Port 7801
./start_backend.ps1
```

### 只启动前端

```powershell
cd frontend
npm install
npm run dev
```

开发代理默认把 `/api/*` 转发到 `http://127.0.0.1:7800`。

## Python legacy 环境准备

先从示例环境文件开始：

```powershell
Copy-Item plantbackend/.env.example plantbackend/.env
```

至少需要修改 `plantbackend/.env` 里的管理员初始密码。

典型手动启动方式：

```powershell
cd plantbackend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m uvicorn asgi:app --host 127.0.0.1 --port 7801
```

## Docker 部署

```powershell
cd deploy
Copy-Item backend.env.example backend.env
```

先把 `deploy/backend.env` 里的 `BOOTSTRAP_ADMIN_PASSWORD` 改掉，再执行：

```powershell
docker compose -f compose.prod.yml up --build
```

对外端口：

- `5500`：前端
- `7800`：Spring 后端

持久化卷：

- `plant-models`
- `plant-datasets`
- `plant-training-runs`
- `plant-runtime`

## 关键环境变量

### Spring 后端

- `SPRING_SERVER_PORT`
- `LEGACY_BACKEND_BASE_URL`
- `LEGACY_BACKEND_AUTO_START`
- `LEGACY_BACKEND_PORT`
- `LEGACY_BACKEND_PYTHON_PATH`
- `PLANT_BACKEND_ROOT`

### Legacy 后端

完整列表见 `plantbackend/.env.example`。常用项如下：

- `BOOTSTRAP_ADMIN_PASSWORD`
- `MODELS_DIR`
- `AUTH_DB_PATH`
- `ANNOTATION_DATASETS_ROOT`
- `TRAINING_RUNS_DIR`
- `TRAINING_BASE_MODEL`

### 可选 AI 接入

- `AI_API_URL`
- `AI_API_BASE_URL`
- `AI_API_CHAT_PATH`
- `AI_API_KEY`
- `AI_API_MODEL`
- `AI_API_TIMEOUT`
- `AI_API_MAX_IMAGE_BYTES`
- `AI_API_IMAGE_DETAIL`

## 演示素材

`output/demo/` 下保留了可选演示图片、演示数据集和简单演示说明，方便本地展示功能链路。

## 打包与上传

如果要生成一份干净的交付包：

```bash
bash tools/package_release.sh
```

脚本会在 `releases/` 下生成压缩包，并自动排除以下本地文件：

- 虚拟环境
- Maven 与前端构建产物
- 本地数据库
- 本地数据集和训练结果
- 临时日志
- `deploy/backend.env` 这类本地环境文件

生成结果：

- `plant-release-<timestamp>.tar.gz`
- `plant-release-<timestamp>.zip`
- `plant-release-<timestamp>.sha256`

## 不应入库的运行时数据

- `plantbackend/.env`
- `plantbackend/plant_auth.db`
- `plantbackend/models/`
- `plantbackend/annotation_datasets/`
- `plantbackend/training_runs/`
- `backend-spring/target/`
- `frontend/node_modules/`
- `frontend/dist/`
- `releases/`
