# Plant Backend

## 目标

这个目录负责：

- 用户认证与会话
- 植物病害识别接口
- 模型上传、切换与下载
- 标注数据集管理
- 数据增强与训练导出
- AI 处理建议生成

## 当前组织方式

- `app.py`：兼容性入口
- `factory.py`：创建 FastAPI 实例
- `asgi.py`：部署入口
- `__main__.py`：`python -m plantbackend`
- `api_router.py`：当前集中路由与处理逻辑
- `config.py`：环境变量和路径配置
- `metadata.py`：应用名称与描述
- `model_service.py`：ONNX 推理
- `auth_store.py`：SQLite 认证与权限数据
- `ai_advice_service.py`：AI 建议生成

## 启动

```bash
cd plantbackend
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m uvicorn asgi:app --host 127.0.0.1 --port 7800
```

如果本机默认 Python 版本过新，导致 `torch/ultralytics` 无法安装，建议额外准备一个专供训练任务使用的 Python 3.12 环境：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv venv --python 3.12 .venv-train
uv pip install --python .venv-train/bin/python -r requirements.txt
```

后端会优先自动探测 `plantbackend/.venv-train/bin/python` 作为训练子进程解释器；也可以通过 `TRAINING_PYTHON_PATH` 显式指定。

也可以直接运行：

```bash
python3 -m plantbackend
```

如果默认端口 `7800` 已被占用，`python -m plantbackend` 会自动回退到下一个可用端口。

## 环境变量

建议从 `plantbackend/.env.example` 开始：

```bash
cp .env.example .env
```

必须关注的变量：

- `BOOTSTRAP_ADMIN_PASSWORD`
- `ALLOWED_ORIGINS`
- `MODELS_DIR`
- `AUTH_DB_PATH`
- `ANNOTATION_DATASETS_ROOT`
- `TRAINING_RUNS_DIR`

## 后续建议

当前最大的后续拆分点仍然是 `api_router.py`。
推荐下一阶段按下面顺序继续拆：

1. `auth`
2. `models`
3. `annotation`
4. `admin`
5. `predict`

这样不会影响现有启动入口和部署方式。
