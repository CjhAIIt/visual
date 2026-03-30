"""Central configuration for the Plant backend.

This module keeps runtime configuration in one place so local development,
Docker deployment, and future CI pipelines all resolve settings the same way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency during fallback runs
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://localhost:5500",
)


def _load_environment_files() -> None:
    if load_dotenv is None:
        return

    # Root `.env` is convenient for compose deployments; backend-local `.env`
    # keeps the module usable when only `plantbackend/` is shipped.
    for env_path in (PROJECT_ROOT / ".env", BASE_DIR / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _read_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or default).strip()


def _read_int(name: str, default: int) -> int:
    raw = _read_str(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _read_float(name: str, default: float) -> float:
    raw = _read_str(name, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def _resolve_backend_path(value: str | Path) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path.resolve())


def _resolve_python_executable(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def _python_has_training_packages(python_path: Path) -> bool:
    if not python_path.exists():
        return False
    try:
        completed = subprocess.run(
            [str(python_path), "-c", "import onnx, torch, ultralytics"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _read_training_python_path() -> str:
    explicit = _read_str("TRAINING_PYTHON_PATH")
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if not explicit_path.is_absolute():
            explicit_path = BASE_DIR / explicit_path
        return str(explicit_path.absolute())

    candidates = (
        _resolve_python_executable(BASE_DIR / ".venv-train"),
        _resolve_python_executable(PROJECT_ROOT / ".venv-train"),
        _resolve_python_executable(BASE_DIR / ".venv"),
        _resolve_python_executable(PROJECT_ROOT / ".venv"),
    )
    for candidate in candidates:
        if _python_has_training_packages(candidate):
            return str(candidate.absolute())

    python312_path = shutil.which("python3.12")
    if python312_path and _python_has_training_packages(Path(python312_path)):
        return str(Path(python312_path).resolve())

    if _python_has_training_packages(Path(sys.executable)):
        return sys.executable

    return sys.executable


def _read_allowed_origins() -> List[str]:
    raw = _read_str("ALLOWED_ORIGINS")
    if not raw:
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins: List[str] = []
    for item in raw.split(","):
        origin = item.strip()
        if not origin:
            continue
        if origin == "*":
            return ["*"]
        if origin not in origins:
            origins.append(origin)
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


def _backend_path(*parts: str) -> str:
    return str((BASE_DIR.joinpath(*parts)).resolve())


_load_environment_files()


@dataclass(frozen=True)
class Settings:
    api_title: str = _read_str("API_TITLE", "Plant Disease Detection API")
    api_version: str = _read_str("API_VERSION", "1.0.0")
    app_env: str = _read_str("APP_ENV", "development")
    api_host: str = _read_str("API_HOST", "127.0.0.1")
    api_port: int = _read_int("API_PORT", 7800)

    models_dir: str = _resolve_backend_path(_read_str("MODELS_DIR", _backend_path("models")))
    default_model_name: str = _read_str("DEFAULT_MODEL_NAME", "best.onnx")
    model_path: str = _resolve_backend_path(
        _read_str("MODEL_PATH", _backend_path("models", _read_str("DEFAULT_MODEL_NAME", "best.onnx")))
    )
    class_names_path: str = _resolve_backend_path(_read_str("CLASS_NAMES_PATH", _backend_path("class_names.json")))
    input_width: int = _read_int("MODEL_INPUT_WIDTH", 640)
    input_height: int = _read_int("MODEL_INPUT_HEIGHT", 640)
    top_k: int = _read_int("TOP_K", 3)
    confidence_threshold: float = _read_float("CONFIDENCE_THRESHOLD", 0.10)
    iou_threshold: float = _read_float("IOU_THRESHOLD", 0.45)

    annotation_datasets_root: str = _resolve_backend_path(
        _read_str("ANNOTATION_DATASETS_ROOT", _backend_path("annotation_datasets"))
    )
    auth_db_path: str = _resolve_backend_path(_read_str("AUTH_DB_PATH", _backend_path("plant_auth.db")))
    auth_session_hours: int = _read_int("AUTH_SESSION_HOURS", 168)
    default_annotation_dataset_name: str = _read_str("DEFAULT_ANNOTATION_DATASET_NAME", "default")

    augment_script_path: str = _resolve_backend_path(_read_str("AUGMENT_SCRIPT_PATH", _backend_path("augment_yolo.py")))
    augmentation_algorithms_dir: str = _resolve_backend_path(
        _read_str("AUGMENTATION_ALGORITHMS_DIR", _backend_path("augmentation_algorithms"))
    )
    active_augmentation_script_record: str = _resolve_backend_path(
        _read_str("ACTIVE_AUGMENTATION_SCRIPT_RECORD", _backend_path("active_augmentation_script.txt"))
    )
    augment_copies: int = _read_int("AUGMENT_COPIES", 3)
    augment_train_ratio: float = _read_float("AUGMENT_TRAIN_RATIO", 0.8)
    augment_seed: int = _read_int("AUGMENT_SEED", 42)

    train_script_path: str = _resolve_backend_path(_read_str("TRAIN_SCRIPT_PATH", _backend_path("train_yolo.py")))
    training_python_path: str = _read_training_python_path()
    training_runs_dir: str = _resolve_backend_path(_read_str("TRAINING_RUNS_DIR", _backend_path("training_runs")))
    training_base_model: str = _read_str("TRAINING_BASE_MODEL", "yolov8n.pt")
    training_epochs: int = _read_int("TRAINING_EPOCHS", 30)
    training_imgsz: int = _read_int("TRAINING_IMGSZ", 640)
    training_workers: int = _read_int("TRAINING_WORKERS", 0)
    training_patience: int = _read_int("TRAINING_PATIENCE", 20)
    training_device: str = _read_str("TRAINING_DEVICE", "")

    ai_api_url: str = _read_str("AI_API_URL", "")
    ai_api_base_url: str = _read_str("AI_API_BASE_URL", "")
    ai_api_chat_path: str = _read_str("AI_API_CHAT_PATH", "/v1/chat/completions")
    ai_api_key: str = _read_str("AI_API_KEY", "")
    ai_api_model: str = _read_str("AI_API_MODEL", "")
    ai_api_timeout: int = _read_int("AI_API_TIMEOUT", 25)
    ai_api_max_image_bytes: int = _read_int("AI_API_MAX_IMAGE_BYTES", 6 * 1024 * 1024)
    ai_api_image_detail: str = _read_str("AI_API_IMAGE_DETAIL", "auto")

    max_upload_bytes: int = _read_int("MAX_UPLOAD_BYTES", 512 * 1024 * 1024)
    max_zip_members: int = _read_int("MAX_ZIP_MEMBERS", 20_000)
    max_zip_uncompressed_bytes: int = _read_int("MAX_ZIP_UNCOMPRESSED_BYTES", 2 * 1024 * 1024 * 1024)
    allowed_origins: Optional[List[str]] = None


settings = Settings(allowed_origins=_read_allowed_origins())
