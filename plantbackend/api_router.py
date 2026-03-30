"""Route registration and request handlers for the Plant backend.

The business logic is still large in this module today, but the application
factory now lives in `app.py`, which gives us a clean deployment entrypoint
and a safer path for future router-by-router extraction.
"""

import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
import csv
from collections import deque
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Callable, Deque, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from starlette.background import BackgroundTask

try:
    from .admin_asset_service import (
        build_builtin_augmentation_item,
        list_managed_augmentation_scripts,
        list_managed_models,
        save_uploaded_file,
    )
    from .ai_advice_service import AiAdviceService
    from .augmentation_manager import (
        clear_active_augmentation_override,
        ensure_augmentation_algorithms_dir,
        get_active_augmentation_script_path,
        get_builtin_augmentation_script_path,
        read_active_augmentation_override,
        resolve_unique_augmentation_script_target,
        write_augmentation_metadata,
        write_active_augmentation_override,
    )
    from .auth_store import AuthStore
    from .config import settings
    from .model_service import ModelService
    from .schemas import (
        AdminConsoleData,
        AdminConsoleResponse,
        AiAdviceData,
        AiRecommendationRequest,
        AiRecommendationResponse,
        AnnotationAugmentData,
        AnnotationAugmentRequest,
        AnnotationBoxItem,
        AnnotationAugmentResponse,
        AnnotationClassCreateRequest,
        AnnotationClassTemplateItem,
        AnnotationClassDeleteRequest,
        AnnotationDatasetItem,
        AnnotationSourceImageDetailData,
        AnnotationSourceImageDetailResponse,
        AnnotationSourceImageItem,
        ClassAdviceData,
        AnnotationClassesData,
        AnnotationClassesResponse,
        AnnotationDatasetCreateRequest,
        AnnotationDatasetDeleteRequest,
        AnnotationSaveData,
        AnnotationSaveResponse,
        AuthLoginRequest,
        AuthRegisterRequest,
        AuthSessionData,
        AuthSessionResponse,
        HealthData,
        HealthResponse,
        ModelTrainData,
        ModelTrainRequest,
        ModelTrainResponse,
        ModelTrainTaskData,
        ModelTrainTaskResponse,
        ManagedAugmentationItem,
        ManagedDatasetItem,
        ManagedModelItem,
        ModelAccessItem,
        ModelDeleteRequest,
        ModelsData,
        ModelsResponse,
        PredictData,
        PredictResponse,
        ToggleValueRequest,
        UserProfile,
        UsersData,
        UsersResponse,
    )
except ImportError:
    from admin_asset_service import (
        build_builtin_augmentation_item,
        list_managed_augmentation_scripts,
        list_managed_models,
        save_uploaded_file,
    )
    from ai_advice_service import AiAdviceService
    
    from augmentation_manager import (
        clear_active_augmentation_override,
        ensure_augmentation_algorithms_dir,
        get_active_augmentation_script_path,
        get_builtin_augmentation_script_path,
        read_active_augmentation_override,
        resolve_unique_augmentation_script_target,
        write_augmentation_metadata,
        write_active_augmentation_override,
    )
    from auth_store import AuthStore
    from config import settings
    from model_service import ModelService
    from schemas import (
        AdminConsoleData,
        AdminConsoleResponse,
        AiAdviceData,
        AiRecommendationRequest,
        AiRecommendationResponse,
        AnnotationAugmentData,
        AnnotationAugmentRequest,
        AnnotationBoxItem,
        AnnotationAugmentResponse,
        AnnotationClassCreateRequest,
        AnnotationClassTemplateItem,
        AnnotationClassDeleteRequest,
        AnnotationDatasetItem,
        AnnotationSourceImageDetailData,
        AnnotationSourceImageDetailResponse,
        AnnotationSourceImageItem,
        ClassAdviceData,
        AnnotationClassesData,
        AnnotationClassesResponse,
        AnnotationDatasetCreateRequest,
        AnnotationDatasetDeleteRequest,
        AnnotationSaveData,
        AnnotationSaveResponse,
        AuthLoginRequest,
        AuthRegisterRequest,
        AuthSessionData,
        AuthSessionResponse,
        HealthData,
        HealthResponse,
        ModelTrainData,
        ModelTrainRequest,
        ModelTrainResponse,
        ModelTrainTaskData,
        ModelTrainTaskResponse,
        ManagedAugmentationItem,
        ManagedDatasetItem,
        ManagedModelItem,
        ModelAccessItem,
        ModelDeleteRequest,
        ModelsData,
        ModelsResponse,
        PredictData,
        PredictResponse,
        ToggleValueRequest,
        UserProfile,
        UsersData,
        UsersResponse,
    )


IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
UNSUPPORTED_VECTOR_IMAGE_TYPES = {"image/svg+xml"}

# Keep one shared router here for now; future refactors can split this module
# into auth, models, annotation, admin, and prediction routers without
# changing the public ASGI entrypoint.
router = APIRouter()

model_service = ModelService()
ai_advice_service = AiAdviceService()
auth_store = AuthStore(settings.auth_db_path, settings.auth_session_hours)
TRAIN_PROGRESS_PREFIX = "__TRAIN_PROGRESS__"
TRAINING_TASKS: Dict[str, Dict[str, object]] = {}
TRAINING_TASKS_LOCK = threading.Lock()
ACTIVE_TRAINING_TASK_ID: Optional[str] = None

ANNOTATION_CLASS_TEMPLATE_SPECS = (
    {
        "key": "blank",
        "label": "空白模板",
        "description": "从零开始搭建类别库，只保留当前数据集真正需要的标注类。",
        "prefixes": (),
    },
    {
        "key": "universal",
        "label": "通用病害库",
        "description": "完整基础病害类别，适合综合识别基线或混合作物数据集。",
        "prefixes": None,
    },
    {
        "key": "apple",
        "label": "苹果病害",
        "description": "苹果叶片与病害检测类。",
        "prefixes": ("Apple",),
    },
    {
        "key": "corn",
        "label": "玉米病害",
        "description": "玉米叶片与病害检测类。",
        "prefixes": ("Corn",),
    },
    {
        "key": "tomato",
        "label": "番茄病害",
        "description": "番茄叶片与病害检测类。",
        "prefixes": ("Tomato",),
    },
    {
        "key": "potato",
        "label": "马铃薯病害",
        "description": "马铃薯叶片与病害检测类。",
        "prefixes": ("Potato",),
    },
    {
        "key": "grape",
        "label": "葡萄病害",
        "description": "葡萄叶片与病害检测类。",
        "prefixes": ("grape",),
    },
    {
        "key": "pepper",
        "label": "甜椒病害",
        "description": "甜椒叶片与病害检测类。",
        "prefixes": ("Bell_pepper",),
    },
    {
        "key": "soybean",
        "label": "大豆病害",
        "description": "大豆叶片与病害检测类。",
        "prefixes": ("Soybean", "Soyabean"),
    },
    {
        "key": "berry",
        "label": "浆果作物",
        "description": "蓝莓、草莓、树莓等浆果作物病害类。",
        "prefixes": ("Blueberry", "Strawberry", "Raspberry"),
    },
)


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_freeform_list(raw_value: Optional[str]) -> List[str]:
    if not raw_value:
        return []
    parts = re.split(r"[,，/\n]+", str(raw_value))
    deduped: List[str] = []
    for item in parts:
        normalized = str(item).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def ensure_supported_uploaded_image(file: UploadFile) -> None:
    content_type = str(file.content_type or "").strip().lower()
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="当前只支持上传图片文件。")
    if content_type in UNSUPPORTED_VECTOR_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="当前暂不支持 SVG 图片，请改用 PNG、JPG、BMP、TIFF 或 WebP。")


def parse_timestamp(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def build_cached_advice_detail(record: Dict[str, object]) -> Optional[str]:
    parts = ["知识库缓存"]
    original_source = str(record.get("source") or "").strip()
    if original_source:
        parts.append(f"原始生成：{original_source}")
    generated_at = parse_timestamp(record.get("updated_at") or record.get("created_at"))
    if generated_at:
        parts.append(f"更新时间：{generated_at.astimezone().isoformat(timespec='seconds')}")
    original_detail = str(record.get("detail") or "").strip()
    if original_detail:
        parts.append(original_detail)
    return "；".join(part for part in parts if part) or None


def to_class_advice_data(record: Dict[str, object]) -> ClassAdviceData:
    generated_at = parse_timestamp(record.get("updated_at") or record.get("created_at"))
    return ClassAdviceData(
        class_name=str(record.get("class_name") or ""),
        summary=str(record.get("summary") or ""),
        advice=[str(item).strip() for item in record.get("advice", []) if str(item).strip()],
        source="knowledge-base",
        detail=build_cached_advice_detail(record),
        generated_at=generated_at.astimezone().isoformat(timespec="seconds") if generated_at else None,
    )


def to_ai_advice_data(payload: Dict[str, object], disease_label: str) -> AiAdviceData:
    return AiAdviceData(
        disease_label=str(payload.get("disease_label") or disease_label or "No detection"),
        summary=str(payload.get("summary") or ""),
        advice=[str(item).strip() for item in payload.get("advice", []) if str(item).strip()],
        source=str(payload.get("source") or "builtin"),
        detail=str(payload.get("detail") or "").strip() or None,
    )


def build_cached_ai_advice(record: Dict[str, object], disease_label: str) -> AiAdviceData:
    return AiAdviceData(
        disease_label=str(disease_label or record.get("class_name") or "No detection"),
        summary=str(record.get("summary") or ""),
        advice=[str(item).strip() for item in record.get("advice", []) if str(item).strip()],
        source="knowledge-base",
        detail=build_cached_advice_detail(record),
    )


def lookup_cached_class_advice(disease_label: str, dataset_name: Optional[str] = None) -> Optional[Dict[str, object]]:
    safe_label = str(disease_label or "").strip()
    if not safe_label or safe_label == "No detection":
        return None
    if dataset_name:
        cached = auth_store.get_class_advice(dataset_name, safe_label)
        if cached:
            return cached
    return auth_store.get_latest_class_advice(safe_label)


def ensure_annotation_class_ai_advice(
    dataset_name: str,
    class_name: str,
    current_user: Dict[str, object],
) -> ClassAdviceData:
    cached = auth_store.get_class_advice(dataset_name, class_name)
    if cached:
        return to_class_advice_data(cached)

    inherited = auth_store.get_latest_class_advice(class_name)
    if inherited:
        auth_store.upsert_class_advice(
            dataset_name=dataset_name,
            class_name=class_name,
            summary=str(inherited.get("summary") or ""),
            advice=[str(item).strip() for item in inherited.get("advice", []) if str(item).strip()],
            source=str(inherited.get("source") or "builtin"),
            detail=str(inherited.get("detail") or "").strip() or None,
            generated_by_user_id=int(current_user["id"]),
        )
        copied = auth_store.get_class_advice(dataset_name, class_name)
        if copied:
            return to_class_advice_data(copied)

    generated_payload = ai_advice_service.generate_class_knowledge(class_name)
    auth_store.upsert_class_advice(
        dataset_name=dataset_name,
        class_name=class_name,
        summary=str(generated_payload.get("summary") or ""),
        advice=[str(item).strip() for item in generated_payload.get("advice", []) if str(item).strip()],
        source=str(generated_payload.get("source") or "builtin"),
        detail=str(generated_payload.get("detail") or "").strip() or None,
        generated_by_user_id=int(current_user["id"]),
    )
    stored = auth_store.get_class_advice(dataset_name, class_name)
    if not stored:
        raise RuntimeError(f"类别建议缓存失败：{class_name}")
    return to_class_advice_data(stored)


def build_dataset_class_advices(dataset_name: str, class_names: List[str]) -> List[ClassAdviceData]:
    advice_items: List[ClassAdviceData] = []
    for class_name in class_names:
        cached = auth_store.get_class_advice(dataset_name, class_name) or auth_store.get_latest_class_advice(class_name)
        if cached:
            advice_items.append(to_class_advice_data(cached))
    return advice_items


def generate_ai_advice(
    disease_label: str,
    confidence: float = 0.0,
    top_predictions: Optional[List[Dict[str, object]]] = None,
    image_bytes: Optional[bytes] = None,
    image_content_type: Optional[str] = None,
    dataset_name: Optional[str] = None,
) -> AiAdviceData:
    cached = lookup_cached_class_advice(disease_label, dataset_name=dataset_name)
    if cached:
        return build_cached_ai_advice(cached, disease_label)

    payload = ai_advice_service.generate(
        disease_label=disease_label,
        confidence=confidence,
        top_predictions=top_predictions or [],
        image_bytes=image_bytes,
        image_content_type=image_content_type,
    )
    return to_ai_advice_data(payload, disease_label)


def user_is_admin(user: Dict[str, object]) -> bool:
    return str(user.get("role") or "") == "admin"


def build_user_profile(user: Dict[str, object]) -> UserProfile:
    dataset_count = int(user.get("dataset_count") or auth_store.count_datasets_for_user(user))
    model_count = int(user.get("model_count") or auth_store.count_models_for_user(user))
    return UserProfile(
        id=int(user["id"]),
        username=str(user["username"]),
        display_name=str(user.get("display_name") or user["username"]),
        role=str(user.get("role") or "user"),
        dataset_count=dataset_count,
        model_count=model_count,
        is_disabled=bool(user.get("is_disabled")),
        is_flagged=bool(user.get("is_flagged")),
    )


def get_current_user(x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token")) -> Dict[str, object]:
    user = auth_store.get_user_by_token(x_auth_token or "")
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效或未登录，请重新登录。")
    return user


def get_optional_current_user(
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
) -> Optional[Dict[str, object]]:
    if not x_auth_token:
        return None
    return auth_store.get_user_by_token(x_auth_token)


def require_admin(current_user: Dict[str, object] = Depends(get_current_user)) -> Dict[str, object]:
    if not user_is_admin(current_user):
        raise HTTPException(status_code=403, detail="只有管理员可以访问该接口。")
    return current_user


def sync_annotation_dataset_registry() -> None:
    root = ensure_annotation_root()
    admin_user = auth_store.get_primary_admin_user()
    if not admin_user:
        return
    for path in root.iterdir():
        if path.is_dir():
            auth_store.ensure_dataset_access_entry(path.name, int(admin_user["id"]), is_public=False)


def sync_model_registry() -> None:
    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    admin_user = auth_store.get_primary_admin_user()
    if not admin_user:
        return
    for path in models_dir.glob("*.onnx"):
        if path.is_file() and path.stat().st_size > 0:
            auth_store.ensure_model_owner(path.name, int(admin_user["id"]), is_public=True)


def user_owns_asset(asset_owner: Optional[Dict[str, object]], current_user: Dict[str, object]) -> bool:
    if not asset_owner:
        return False
    return int(asset_owner.get("owner_user_id") or -1) == int(current_user["id"])


def can_read_dataset(dataset_owner: Optional[Dict[str, object]], current_user: Dict[str, object]) -> bool:
    if user_is_admin(current_user):
        return True
    if user_owns_asset(dataset_owner, current_user):
        return True
    return bool(dataset_owner and dataset_owner.get("is_public"))


def can_write_dataset(dataset_owner: Optional[Dict[str, object]], current_user: Dict[str, object]) -> bool:
    return user_is_admin(current_user) or user_owns_asset(dataset_owner, current_user)


def can_read_model(model_owner: Optional[Dict[str, object]], current_user: Dict[str, object]) -> bool:
    if user_is_admin(current_user):
        return True
    if user_owns_asset(model_owner, current_user):
        return True
    return bool(model_owner and model_owner.get("is_public"))


def can_manage_model(model_owner: Optional[Dict[str, object]], current_user: Dict[str, object]) -> bool:
    return user_is_admin(current_user) or user_owns_asset(model_owner, current_user)


def build_managed_dataset_item(dataset_record: Dict[str, object], current_user: Dict[str, object]) -> ManagedDatasetItem:
    return ManagedDatasetItem(
        name=str(dataset_record.get("dataset_name") or ""),
        uploaded_at=str(dataset_record.get("created_at")) if dataset_record.get("created_at") else None,
        is_public=bool(dataset_record.get("is_public")),
        is_official=str(dataset_record.get("owner_role") or "") == "admin",
        can_manage=can_write_dataset(dataset_record, current_user),
        owner_username=str(dataset_record.get("owner_username")) if dataset_record.get("owner_username") else None,
        owner_display_name=str(dataset_record.get("owner_display_name")) if dataset_record.get("owner_display_name") else None,
    )


def build_annotation_dataset_item(dataset_name: str, current_user: Dict[str, object]) -> AnnotationDatasetItem:
    dataset_owner = auth_store.get_dataset_owner(dataset_name)
    return AnnotationDatasetItem(
        name=dataset_name,
        is_public=bool(dataset_owner and dataset_owner.get("is_public")),
        is_official=bool(dataset_owner and str(dataset_owner.get("owner_role") or "") == "admin"),
        can_write=can_write_dataset(dataset_owner, current_user),
        owner_username=str(dataset_owner.get("owner_username")) if dataset_owner and dataset_owner.get("owner_username") else None,
        owner_display_name=str(dataset_owner.get("owner_display_name")) if dataset_owner and dataset_owner.get("owner_display_name") else None,
    )


def build_model_access_item(model_name: str, current_user: Dict[str, object]) -> ModelAccessItem:
    model_owner = auth_store.get_model_owner(model_name)
    is_active = model_service.current_model_name == model_name
    if not is_active:
        preferred_model = get_preferred_model_name_for_user(current_user)
        is_active = preferred_model == model_name
    return ModelAccessItem(
        name=model_name,
        is_active=is_active,
        is_public=bool(model_owner and model_owner.get("is_public")),
        is_official=bool(model_owner and str(model_owner.get("owner_role") or "") == "admin"),
        can_manage=can_manage_model(model_owner, current_user),
        owner_username=str(model_owner.get("owner_username")) if model_owner and model_owner.get("owner_username") else None,
        owner_display_name=str(model_owner.get("owner_display_name")) if model_owner and model_owner.get("owner_display_name") else None,
    )


def get_default_dataset_name_for_user(user: Dict[str, object]) -> str:
    if user_is_admin(user):
        return safe_annotation_dataset_name(settings.default_annotation_dataset_name)
    return safe_annotation_dataset_name(f"{user['username']}_{settings.default_annotation_dataset_name}")


def raise_dataset_not_found(dataset_key: str) -> None:
    raise HTTPException(status_code=404, detail=f"数据集不存在：{dataset_key}")


def raise_dataset_name_unavailable() -> None:
    raise RuntimeError("当前数据集名称不可用，请更换一个新名称。")


def ensure_dataset_access(dataset_name: Optional[str], current_user: Dict[str, object], allow_auto_create: bool = False) -> str:
    requested_name = dataset_name or get_default_dataset_name_for_user(current_user)
    dataset_key = safe_annotation_dataset_name(requested_name)
    sync_annotation_dataset_registry()
    owner = auth_store.get_dataset_owner(dataset_key)
    structure = get_annotation_dataset_structure(dataset_key)

    if owner:
        if can_read_dataset(owner, current_user):
            return dataset_key
        raise_dataset_not_found(dataset_key)

    if user_is_admin(current_user) and structure["dataset_dir"].exists():
        auth_store.ensure_dataset_access_entry(dataset_key, int(current_user["id"]), is_public=False)
        return dataset_key

    if allow_auto_create:
        return create_annotation_dataset(dataset_key, current_user, is_public=False)

    raise_dataset_not_found(dataset_key)


def ensure_dataset_write_access(dataset_name: Optional[str], current_user: Dict[str, object], allow_auto_create: bool = False) -> str:
    requested_name = dataset_name or get_default_dataset_name_for_user(current_user)
    dataset_key = safe_annotation_dataset_name(requested_name)
    sync_annotation_dataset_registry()
    owner = auth_store.get_dataset_owner(dataset_key)
    structure = get_annotation_dataset_structure(dataset_key)

    if owner:
        if can_write_dataset(owner, current_user):
            return dataset_key
        raise_dataset_not_found(dataset_key)

    if user_is_admin(current_user) and structure["dataset_dir"].exists():
        auth_store.ensure_dataset_access_entry(dataset_key, int(current_user["id"]), is_public=False)
        return dataset_key

    if allow_auto_create:
        return create_annotation_dataset(dataset_key, current_user, is_public=False)

    raise_dataset_not_found(dataset_key)


def list_accessible_model_names(current_user: Dict[str, object]) -> List[str]:
    sync_model_registry()
    available_models = get_release_visible_model_names(model_service.available_models())
    if user_is_admin(current_user):
        return available_models
    accessible_models = set(auth_store.list_accessible_model_names_for_user(int(current_user["id"])))
    return [model_name for model_name in available_models if model_name in accessible_models]


def get_release_visible_model_names(model_names: List[str]) -> List[str]:
    normalized_names = sorted({Path(model_name).name for model_name in model_names if model_name})
    best_names: List[str] = []
    if "best.onnx" in normalized_names:
        best_names.append("best.onnx")
    best_names.extend([
        model_name
        for model_name in normalized_names
        if model_name != "best.onnx" and re.fullmatch(r"best(?:\(\d+\))?\.onnx", model_name, flags=re.IGNORECASE)
    ])
    if best_names:
        return best_names[:2]
    return normalized_names[:2]


def get_preferred_model_name_for_user(current_user: Dict[str, object], accessible_models: Optional[List[str]] = None) -> Optional[str]:
    model_names = accessible_models if accessible_models is not None else list_accessible_model_names(current_user)
    if not model_names:
        return None
    if model_service.current_model_name in model_names:
        return model_service.current_model_name
    return model_names[0]


def ensure_model_access(model_name: str, current_user: Dict[str, object]) -> str:
    sync_model_registry()
    normalized_name = Path(model_name or "").name
    if normalized_name not in model_service.available_models():
        raise HTTPException(status_code=404, detail=f"模型不存在：{normalized_name}")

    model_owner = auth_store.get_model_owner(normalized_name)
    if not can_read_model(model_owner, current_user):
        raise HTTPException(status_code=403, detail=f"你没有权限访问模型：{normalized_name}")
    return normalized_name


def resolve_predict_model_name(requested_model_name: Optional[str], current_user: Dict[str, object]) -> str:
    if requested_model_name:
        return ensure_model_access(requested_model_name, current_user)

    preferred_model = get_preferred_model_name_for_user(current_user)
    if preferred_model:
        return preferred_model
    raise HTTPException(status_code=404, detail="当前没有你可访问的模型，请联系管理员上传公开模型或使用你自己的模型。")


def estimate_task_timing(task: Dict[str, object]) -> Tuple[Optional[int], Optional[str]]:
    status = str(task.get("status") or "")
    if status == "completed":
        finished_at = str(task.get("updated_at") or "") or current_timestamp()
        return 0, finished_at
    if status != "running":
        return None, None

    progress = max(0.0, min(float(task.get("progress") or 0.0), 1.0))
    current_epoch = int(task["current_epoch"]) if task.get("current_epoch") is not None else None
    started_at = parse_timestamp(task.get("started_at"))
    updated_at = parse_timestamp(task.get("updated_at")) or datetime.now().astimezone()
    if not started_at or progress <= 0.0 or progress >= 1.0:
        return None, None
    if current_epoch is not None and current_epoch <= 0:
        return None, None

    elapsed_seconds = max(1.0, (updated_at - started_at).total_seconds())
    eta_seconds = max(0, int(round(elapsed_seconds * (1.0 - progress) / progress)))
    estimated_finish_at = (updated_at + timedelta(seconds=eta_seconds)).isoformat(timespec="seconds")
    return eta_seconds, estimated_finish_at


def build_train_task_data(task: Dict[str, object]) -> ModelTrainTaskData:
    result = task.get("result")
    if isinstance(result, dict):
        result = ModelTrainData(**result)

    eta_seconds, estimated_finish_at = estimate_task_timing(task)

    return ModelTrainTaskData(
        task_id=str(task.get("task_id") or ""),
        dataset_name=str(task.get("dataset_name") or ""),
        status=str(task.get("status") or "queued"),
        progress=max(0.0, min(float(task.get("progress") or 0.0), 1.0)),
        stage=str(task.get("stage") or "queued"),
        message=str(task.get("message") or ""),
        current_epoch=int(task["current_epoch"]) if task.get("current_epoch") is not None else None,
        total_epochs=int(task["total_epochs"]) if task.get("total_epochs") is not None else None,
        created_at=str(task.get("created_at")) if task.get("created_at") else None,
        started_at=str(task.get("started_at")) if task.get("started_at") else None,
        updated_at=str(task.get("updated_at")) if task.get("updated_at") else None,
        eta_seconds=eta_seconds,
        estimated_finish_at=estimated_finish_at,
        error=str(task.get("error")) if task.get("error") else None,
        result=result if isinstance(result, ModelTrainData) else None,
    )


def set_train_task_state(task_id: str, **changes: object) -> None:
    with TRAINING_TASKS_LOCK:
        task = TRAINING_TASKS.get(task_id)
        if not task:
            return
        timestamp = current_timestamp()
        changes.setdefault("updated_at", timestamp)
        next_status = str(changes.get("status") or task.get("status") or "")
        if next_status == "running" and not task.get("started_at") and "started_at" not in changes:
            changes["started_at"] = timestamp
        task.update(changes)


def get_train_task_data(task_id: str, current_user: Dict[str, object]) -> ModelTrainTaskData:
    with TRAINING_TASKS_LOCK:
        task = TRAINING_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"训练任务不存在：{task_id}")
        if (not user_is_admin(current_user)) and int(task.get("owner_user_id") or -1) != int(current_user["id"]):
            raise HTTPException(status_code=403, detail="你没有权限查看这个训练任务。")
        snapshot = dict(task)
    return build_train_task_data(snapshot)


def ensure_no_active_training_task() -> None:
    global ACTIVE_TRAINING_TASK_ID

    with TRAINING_TASKS_LOCK:
        if not ACTIVE_TRAINING_TASK_ID:
            return

        active_task = TRAINING_TASKS.get(ACTIVE_TRAINING_TASK_ID)
        if active_task and str(active_task.get("status") or "") in {"queued", "running"}:
            dataset_name = str(active_task.get("dataset_name") or "当前数据集")
            raise HTTPException(
                status_code=409,
                detail=f"已有训练任务正在执行：{dataset_name}（task_id={ACTIVE_TRAINING_TASK_ID}）。请等待当前训练完成后再试。",
            )

        ACTIVE_TRAINING_TASK_ID = None


def run_training_command(
    command: List[str],
    progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_tail: Deque[str] = deque(maxlen=40)

    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                output_tail.append(line)
                if progress_callback and line.startswith(TRAIN_PROGRESS_PREFIX):
                    payload_text = line[len(TRAIN_PROGRESS_PREFIX):]
                    try:
                        payload = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        progress_callback(payload)
    finally:
        if process.stdout is not None:
            process.stdout.close()

    return_code = process.wait()
    if return_code != 0:
        detail = "\n".join(output_tail).strip() or "模型训练失败。"
        raise HTTPException(status_code=500, detail=detail)


def start_training_task(
    dataset_name: str,
    base_model: str,
    requested_model_name: Optional[str],
    epochs: int,
    imgsz: int,
    current_user: Dict[str, object],
) -> ModelTrainTaskData:
    global ACTIVE_TRAINING_TASK_ID

    ensure_no_active_training_task()
    task_id = uuid.uuid4().hex
    created_at = current_timestamp()
    task_state: Dict[str, object] = {
        "task_id": task_id,
        "dataset_name": ensure_dataset_access(dataset_name, current_user, allow_auto_create=False),
        "status": "queued",
        "progress": 0.0,
        "stage": "queued",
        "message": "训练任务已创建，等待启动。",
        "current_epoch": 0,
        "total_epochs": max(1, int(epochs)),
        "created_at": created_at,
        "started_at": None,
        "updated_at": created_at,
        "error": None,
        "result": None,
        "owner_user_id": int(current_user["id"]),
        "owner_username": str(current_user["username"]),
    }

    with TRAINING_TASKS_LOCK:
        TRAINING_TASKS[task_id] = task_state
        ACTIVE_TRAINING_TASK_ID = task_id

    def task_worker() -> None:
        global ACTIVE_TRAINING_TASK_ID

        def handle_progress(payload: Dict[str, object]) -> None:
            progress_value = payload.get("progress")
            current_epoch = payload.get("current_epoch")
            total_epochs = payload.get("total_epochs")
            stage = str(payload.get("stage") or "training")
            message = str(payload.get("message") or "训练进行中。")

            set_train_task_state(
                task_id,
                status="running",
                progress=max(0.0, min(float(progress_value or 0.0), 1.0)),
                stage=stage,
                message=message,
                current_epoch=int(current_epoch) if current_epoch is not None else None,
                total_epochs=int(total_epochs) if total_epochs is not None else max(1, int(epochs)),
                error=None,
            )

        try:
            set_train_task_state(
                task_id,
                status="running",
                progress=0.01,
                stage="preparing",
                message="正在准备训练数据和运行环境。",
                current_epoch=0,
                total_epochs=max(1, int(epochs)),
                error=None,
            )
            result = train_model_and_export(
                dataset_name,
                base_model,
                requested_model_name,
                epochs,
                imgsz,
                current_user,
                progress_callback=handle_progress,
            )
            set_train_task_state(
                task_id,
                status="completed",
                progress=1.0,
                stage="completed",
                message=f"数据集 {result.dataset_name} 训练完成，模型已导出。",
                current_epoch=result.epochs,
                total_epochs=result.epochs,
                error=None,
                result=result,
            )
        except HTTPException as exc:
            detail = str(exc.detail)
            set_train_task_state(
                task_id,
                status="failed",
                stage="failed",
                message=detail,
                error=detail,
            )
        except Exception as exc:
            detail = str(exc) or "模型训练失败"
            set_train_task_state(
                task_id,
                status="failed",
                stage="failed",
                message=detail,
                error=detail,
            )
        finally:
            with TRAINING_TASKS_LOCK:
                if ACTIVE_TRAINING_TASK_ID == task_id:
                    ACTIVE_TRAINING_TASK_ID = None

    threading.Thread(target=task_worker, name=f"train-task-{task_id}", daemon=True).start()
    return build_train_task_data(dict(task_state))


def load_base_annotation_classes() -> List[str]:
    class_names_path = Path(settings.class_names_path)
    if not class_names_path.exists():
        raise RuntimeError(f"类别名称文件不存在：{class_names_path}")

    try:
        raw = json.loads(class_names_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"类别名称文件格式无效：{class_names_path}") from exc

    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise RuntimeError("类别名称文件必须是非空字符串数组。")

    return raw


def build_annotation_class_templates(base_classes: List[str]) -> List[AnnotationClassTemplateItem]:
    deduped_classes = list(dict.fromkeys(base_classes))
    templates: List[AnnotationClassTemplateItem] = []
    for spec in ANNOTATION_CLASS_TEMPLATE_SPECS:
        prefixes = spec["prefixes"]
        if prefixes is None:
            template_classes = deduped_classes
        elif not prefixes:
            template_classes = []
        else:
            template_classes = [
                class_name
                for class_name in deduped_classes
                if any(class_name.lower().startswith(str(prefix).lower()) for prefix in prefixes)
            ]
        if not template_classes and spec["key"] not in {"blank", "universal"}:
            continue
        templates.append(
            AnnotationClassTemplateItem(
                key=str(spec["key"]),
                label=str(spec["label"]),
                description=str(spec["description"]),
                class_count=len(template_classes),
                classes=template_classes,
            )
        )
    return templates


def list_annotation_class_templates() -> List[AnnotationClassTemplateItem]:
    return build_annotation_class_templates(load_base_annotation_classes())


def get_annotation_class_template(template_key: Optional[str]) -> Optional[AnnotationClassTemplateItem]:
    normalized_key = str(template_key or "").strip().lower()
    if not normalized_key:
        return None
    for template in list_annotation_class_templates():
        if template.key == normalized_key:
            return template
    return None


def detect_annotation_class_template_key(
    classes: List[str],
    templates: Optional[List[AnnotationClassTemplateItem]] = None,
) -> Optional[str]:
    available_templates = templates or list_annotation_class_templates()
    current_set = set(classes)
    if not current_set:
        return "blank"

    for template in available_templates:
        if current_set == set(template.classes):
            return template.key

    focused_matches = [
        template.key
        for template in available_templates
        if template.key not in {"blank", "universal"} and current_set and current_set.issubset(set(template.classes))
    ]
    if len(focused_matches) == 1:
        return focused_matches[0]
    return "custom"


def ensure_annotation_root() -> Path:
    root = Path(settings.annotation_datasets_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_annotation_dataset_name(name: Optional[str]) -> str:
    raw = str(name or "").strip()
    sanitized = re.sub(r'[<>:"/\\|?*]+', "_", raw)
    sanitized = re.sub(r"\s+", "_", sanitized).strip(" ._")
    return sanitized or settings.default_annotation_dataset_name


def normalize_annotation_class_name(name: str) -> str:
    normalized = re.sub(r"\s+", " ", str(name or "").strip())
    if not normalized:
        raise RuntimeError("Custom class name cannot be empty.")
    return normalized


def build_annotation_dataset_structure(dataset_key: str, dataset_dir: Path) -> Dict[str, Path]:
    return {
        "dataset_key": Path(dataset_key),
        "dataset_dir": dataset_dir,
        "images_raw": dataset_dir / "images" / "raw",
        "labels_raw": dataset_dir / "labels" / "raw",
        "images_train": dataset_dir / "images" / "train",
        "labels_train": dataset_dir / "labels" / "train",
        "images_val": dataset_dir / "images" / "val",
        "labels_val": dataset_dir / "labels" / "val",
    }


def get_annotation_dataset_structure(dataset_name: Optional[str] = None) -> Dict[str, Path]:
    dataset_key = safe_annotation_dataset_name(dataset_name)
    dataset_dir = ensure_annotation_root() / dataset_key
    return build_annotation_dataset_structure(dataset_key, dataset_dir)


def ensure_annotation_dataset_structure_at(dataset_key: str, dataset_dir: Path, classes: List[str]) -> Tuple[str, Dict[str, Path]]:
    structure = build_annotation_dataset_structure(dataset_key, dataset_dir)
    structure["dataset_dir"].mkdir(parents=True, exist_ok=True)
    for key in ("images_raw", "labels_raw", "images_train", "labels_train", "images_val", "labels_val"):
        structure[key].mkdir(parents=True, exist_ok=True)

    cleaned_classes = [normalize_annotation_class_name(name) for name in classes]
    (structure["dataset_dir"] / "classes.txt").write_text("\n".join(cleaned_classes), encoding="utf-8")

    names_yaml = "\n".join([f"  {index}: {name}" for index, name in enumerate(cleaned_classes)])
    dataset_yaml = (
        f"path: {structure['dataset_dir'].as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/val\n"
        f"nc: {len(cleaned_classes)}\n"
        "names:\n"
        f"{names_yaml}\n"
    )
    (structure["dataset_dir"] / "dataset.yaml").write_text(dataset_yaml, encoding="utf-8")
    return dataset_key, structure


def ensure_annotation_dataset_structure(dataset_name: Optional[str], classes: List[str]) -> Tuple[str, Dict[str, Path]]:
    dataset_key = safe_annotation_dataset_name(dataset_name)
    dataset_dir = ensure_annotation_root() / dataset_key
    return ensure_annotation_dataset_structure_at(dataset_key, dataset_dir, classes)


def list_annotation_datasets(current_user: Dict[str, object]) -> List[str]:
    sync_annotation_dataset_registry()
    root = ensure_annotation_root()
    directory_names = {
        path.name
        for path in root.iterdir()
        if path.is_dir()
    }
    if user_is_admin(current_user):
        recorded_names = {
            str(item["dataset_name"])
            for item in auth_store.list_all_datasets()
            if item.get("dataset_name")
        }
        dataset_names = sorted(directory_names | recorded_names)
    else:
        recorded_names = {
            str(item["dataset_name"])
            for item in auth_store.list_accessible_datasets_for_user(int(current_user["id"]))
            if item.get("dataset_name")
        }
        accessible_directory_names = {
            dataset_name
            for dataset_name in directory_names
            if can_read_dataset(auth_store.get_dataset_owner(dataset_name), current_user)
        }
        dataset_names = sorted(accessible_directory_names | recorded_names)
    if dataset_names:
        return dataset_names

    return []


def load_annotation_classes(
    dataset_name: Optional[str],
    current_user: Dict[str, object],
    require_write: bool = False,
    allow_auto_create: bool = True,
) -> Tuple[str, List[str], Dict[str, Path]]:
    if require_write:
        dataset_key = ensure_dataset_write_access(dataset_name, current_user, allow_auto_create=allow_auto_create)
    else:
        dataset_key = ensure_dataset_access(dataset_name, current_user, allow_auto_create=allow_auto_create)
    structure = get_annotation_dataset_structure(dataset_key)
    dataset_key = structure["dataset_key"].name
    classes_file = structure["dataset_dir"] / "classes.txt"

    if classes_file.exists():
        classes = [line.strip() for line in classes_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if require_write:
            ensure_annotation_dataset_structure(dataset_key, classes)
        return dataset_key, classes, structure

    base_classes = load_base_annotation_classes()
    if require_write:
        ensure_annotation_dataset_structure(dataset_key, base_classes)
    return dataset_key, base_classes, structure


def build_annotation_classes_response(
    current_user: Dict[str, object],
    dataset_name: Optional[str] = None,
    message: str = "annotation classes available",
) -> AnnotationClassesResponse:
    class_templates = list_annotation_class_templates()
    available_datasets = list_annotation_datasets(current_user)
    available_dataset_items = [build_annotation_dataset_item(dataset, current_user) for dataset in available_datasets]
    requested_dataset = safe_annotation_dataset_name(dataset_name) if dataset_name else ""
    selected_dataset = requested_dataset or (available_datasets[0] if available_datasets else "")

    if not selected_dataset:
        return AnnotationClassesResponse(
            success=True,
            message=message,
            data=AnnotationClassesData(
                selected_dataset="",
                available_datasets=[],
                available_dataset_items=[],
                classes=[],
                class_templates=class_templates,
                class_advices=[],
                dataset_dir="",
                images_dir="",
                labels_dir="",
                source_pair_count=0,
                source_image_count=0,
                annotated_source_count=0,
                source_images=[],
                train_pair_count=0,
                val_pair_count=0,
                selected_dataset_template_key="blank",
                selected_dataset_is_public=False,
                selected_dataset_is_official=False,
                selected_dataset_owner_username=None,
                selected_dataset_owner_display_name=None,
                selected_dataset_can_write=False,
            ),
        )

    selected_dataset, classes, structure = load_annotation_classes(selected_dataset, current_user, allow_auto_create=False)
    if selected_dataset not in available_datasets:
        available_datasets = sorted(set(available_datasets + [selected_dataset]))
        available_dataset_items = [build_annotation_dataset_item(dataset, current_user) for dataset in available_datasets]
    selected_dataset_item = next(
        (item for item in available_dataset_items if item.name == selected_dataset),
        build_annotation_dataset_item(selected_dataset, current_user),
    )
    source_pair_count = count_available_source_pairs(structure)
    source_image_count = count_raw_source_images(structure)
    annotated_source_count = count_annotated_source_images(structure)
    source_images = build_annotation_source_image_items(structure)
    train_pair_count = len(collect_image_label_pairs(structure["images_train"], structure["labels_train"]))
    val_pair_count = len(collect_image_label_pairs(structure["images_val"], structure["labels_val"]))
    return AnnotationClassesResponse(
        success=True,
        message=message,
        data=AnnotationClassesData(
            selected_dataset=selected_dataset,
            available_datasets=available_datasets,
            available_dataset_items=available_dataset_items,
            classes=classes,
            class_templates=class_templates,
            class_advices=build_dataset_class_advices(selected_dataset, classes),
            dataset_dir=str(structure["dataset_dir"]),
            images_dir=str(structure["images_raw"]),
            labels_dir=str(structure["labels_raw"]),
            source_pair_count=source_pair_count,
            source_image_count=source_image_count,
            annotated_source_count=annotated_source_count,
            source_images=source_images,
            train_pair_count=train_pair_count,
            val_pair_count=val_pair_count,
            selected_dataset_template_key=detect_annotation_class_template_key(classes, class_templates),
            selected_dataset_is_public=selected_dataset_item.is_public,
            selected_dataset_is_official=selected_dataset_item.is_official,
            selected_dataset_owner_username=selected_dataset_item.owner_username,
            selected_dataset_owner_display_name=selected_dataset_item.owner_display_name,
            selected_dataset_can_write=selected_dataset_item.can_write,
        ),
    )


def create_annotation_dataset(
    dataset_name: str,
    current_user: Dict[str, object],
    source_dataset: Optional[str] = None,
    is_public: bool = False,
    class_template_key: Optional[str] = None,
) -> str:
    dataset_key = safe_annotation_dataset_name(dataset_name)
    structure = get_annotation_dataset_structure(dataset_key)
    existing_owner = auth_store.get_dataset_owner(dataset_key)
    if existing_owner:
        if int(existing_owner["owner_user_id"]) == int(current_user["id"]):
            auth_store.ensure_dataset_access_entry(
                dataset_key,
                int(current_user["id"]),
                is_public=is_public,
                overwrite_existing=True,
            )
            return dataset_key
        if user_is_admin(current_user):
            auth_store.ensure_dataset_access_entry(
                dataset_key,
                int(existing_owner["owner_user_id"]),
                is_public=is_public,
                overwrite_existing=True,
            )
            return dataset_key
        raise_dataset_name_unavailable()

    if structure["dataset_dir"].exists():
        if user_is_admin(current_user):
            auth_store.ensure_dataset_access_entry(dataset_key, int(current_user["id"]), is_public=is_public, overwrite_existing=True)
            return dataset_key
        raise_dataset_name_unavailable()

    if source_dataset:
        source_classes = load_annotation_classes(source_dataset, current_user)[1]
    elif class_template_key:
        template = get_annotation_class_template(class_template_key)
        if not template:
            raise RuntimeError(f"未知的数据集类别模板：{class_template_key}")
        source_classes = list(template.classes)
    else:
        source_classes = load_base_annotation_classes()
    ensure_annotation_dataset_structure(dataset_key, source_classes)
    auth_store.ensure_dataset_access_entry(dataset_key, int(current_user["id"]), is_public=is_public, overwrite_existing=True)
    return dataset_key


def delete_annotation_dataset(dataset_name: str, current_user: Dict[str, object]) -> str:
    dataset_key = safe_annotation_dataset_name(dataset_name)
    sync_annotation_dataset_registry()
    owner = auth_store.get_dataset_owner(dataset_key)
    structure = get_annotation_dataset_structure(dataset_key)

    if owner:
        if not can_write_dataset(owner, current_user):
            raise_dataset_not_found(dataset_key)
    elif user_is_admin(current_user) and structure["dataset_dir"].exists():
        auth_store.ensure_dataset_access_entry(dataset_key, int(current_user["id"]), is_public=False)
    else:
        raise_dataset_not_found(dataset_key)

    # A dataset may already have been removed from disk by cleanup scripts or
    # manual filesystem operations. In that case we still want the admin UI to
    # be able to clear the stale ownership record.
    if structure["dataset_dir"].is_dir():
        shutil.rmtree(structure["dataset_dir"])
    elif structure["dataset_dir"].exists():
        structure["dataset_dir"].unlink()

    auth_store.delete_dataset_owner(dataset_key)
    remaining = list_annotation_datasets(current_user)
    return remaining[0] if remaining else ""


def append_annotation_class(dataset_name: Optional[str], current_user: Dict[str, object], class_name: str) -> Tuple[str, str, bool]:
    dataset_key, classes, _ = load_annotation_classes(dataset_name, current_user, require_write=True)
    normalized_name = normalize_annotation_class_name(class_name)
    was_created = False
    if normalized_name not in classes:
        classes.append(normalized_name)
        ensure_annotation_dataset_structure(dataset_key, classes)
        was_created = True
    return dataset_key, normalized_name, was_created


def rewrite_labels_after_class_delete(structure: Dict[str, Path], deleted_index: int) -> None:
    for key in ("labels_raw", "labels_train", "labels_val"):
        labels_dir = structure[key]
        if not labels_dir.exists():
            continue

        for label_path in sorted(labels_dir.glob("*.txt")):
            original_lines = label_path.read_text(encoding="utf-8").splitlines()
            updated_lines: List[str] = []

            for line in original_lines:
                stripped = line.strip()
                if not stripped:
                    continue

                parts = stripped.split()
                if len(parts) < 5:
                    updated_lines.append(stripped)
                    continue

                try:
                    class_index = int(parts[0])
                except ValueError:
                    updated_lines.append(stripped)
                    continue

                if class_index == deleted_index:
                    continue
                if class_index > deleted_index:
                    parts[0] = str(class_index - 1)
                updated_lines.append(" ".join(parts))

            label_path.write_text("\n".join(updated_lines), encoding="utf-8")


def delete_annotation_class(dataset_name: Optional[str], current_user: Dict[str, object], class_name: str) -> Tuple[str, str]:
    dataset_key, classes, structure = load_annotation_classes(dataset_name, current_user, require_write=True)
    normalized_name = normalize_annotation_class_name(class_name)
    if normalized_name not in classes:
        raise RuntimeError(f"数据集 {dataset_key} 中不存在该类别：{normalized_name}")
    if len(classes) <= 1:
        raise RuntimeError("数据集中至少要保留一个类别。")

    deleted_index = classes.index(normalized_name)
    rewrite_labels_after_class_delete(structure, deleted_index)
    next_classes = [item for index, item in enumerate(classes) if index != deleted_index]
    ensure_annotation_dataset_structure(dataset_key, next_classes)
    auth_store.delete_class_advice(dataset_key, normalized_name)
    return dataset_key, normalized_name


def safe_annotation_stem(filename: str) -> str:
    stem = Path(filename or "annotation_image").stem
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return sanitized or "annotation_image"


def clear_directory(directory: Path) -> None:
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        return
    for path in directory.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def safe_model_stem(name: Optional[str], fallback: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "").strip())
    raw = re.sub(r"\.onnx$", "", raw, flags=re.IGNORECASE)
    raw = raw.strip("._")
    if raw:
        return raw

    fallback_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._")
    return fallback_stem or "trained_model"


def resolve_unique_model_targets(models_dir: Path, desired_stem: str) -> Tuple[str, Path, Path, Path]:
    stem = desired_stem
    onnx_path = models_dir / f"{stem}.onnx"
    counter = 1
    while onnx_path.exists():
        stem = f"{desired_stem}_{counter}"
        onnx_path = models_dir / f"{stem}.onnx"
        counter += 1

    return (
        stem,
        onnx_path,
        models_dir / f"{stem}.labels.json",
        models_dir / f"{stem}.meta.json",
    )


def copy_directory_contents(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in source_dir.iterdir():
        target_path = target_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target_path)


def extract_zip_archive_safely(archive_path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_root = destination_dir.resolve()
    total_uncompressed_bytes = 0
    with zipfile.ZipFile(archive_path) as archive:
        for index, member in enumerate(archive.infolist(), start=1):
            if index > int(settings.max_zip_members):
                raise RuntimeError("压缩包中文件数量过多，已拒绝导入。")

            file_mode = (int(member.external_attr) >> 16) & 0o170000
            if file_mode == 0o120000:
                raise RuntimeError("压缩包包含符号链接，已拒绝导入。")

            total_uncompressed_bytes += max(0, int(member.file_size or 0))
            if total_uncompressed_bytes > int(settings.max_zip_uncompressed_bytes):
                raise RuntimeError("压缩包解压后的总体积过大，已拒绝导入。")

            relative_name = str(member.filename or "").replace("\\", "/").strip("/")
            if not relative_name:
                continue

            relative_path = Path(relative_name)
            if relative_path.is_absolute() or any(part == ".." for part in relative_path.parts):
                raise RuntimeError("压缩包包含非法路径，已拒绝导入。")

            target_path = (destination_dir / relative_path).resolve()
            try:
                target_path.relative_to(destination_root)
            except ValueError as exc:
                raise RuntimeError("压缩包包含越界路径，已拒绝导入。") from exc

            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source_file, target_path.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)


def resolve_uploaded_dataset_source_root(extract_root: Path) -> Path:
    candidates: List[Path] = [extract_root]
    direct_children = [child for child in extract_root.iterdir() if child.is_dir()]
    if len(direct_children) == 1:
        candidates.insert(0, direct_children[0])
    candidates.extend(direct_children)

    for candidate in candidates:
        has_classes = (candidate / "classes.txt").exists()
        has_images = (candidate / "images").exists()
        has_labels = (candidate / "labels").exists()
        if has_classes or (has_images and has_labels):
            return candidate

    raise RuntimeError("未在压缩包中识别到有效的数据集目录，请确认压缩包内包含 classes.txt 以及 images/labels 结构。")


def read_uploaded_dataset_classes(source_root: Path) -> List[str]:
    classes_path = source_root / "classes.txt"
    if not classes_path.exists():
        raise RuntimeError("上传的数据集缺少 classes.txt，当前仅支持导入包含类别定义的数据集压缩包。")

    classes = [line.strip() for line in classes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not classes:
        raise RuntimeError("上传的数据集 classes.txt 为空。")
    return classes


def normalize_uploaded_dataset_relative_path(raw_path: str) -> Path:
    normalized = str(raw_path or "").replace("\\", "/").strip("/")
    if not normalized:
        raise RuntimeError("上传的数据集文件路径为空。")

    relative_path = Path(normalized)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise RuntimeError("上传的数据集包含非法路径。")
    return relative_path


def infer_uploaded_dataset_name(relative_paths: List[str], fallback_name: str = "dataset_import") -> str:
    normalized_paths = [normalize_uploaded_dataset_relative_path(item) for item in relative_paths if str(item or "").strip()]
    if not normalized_paths:
        return fallback_name

    first_parts = [path.parts[0] for path in normalized_paths if len(path.parts) > 1]
    if first_parts:
        candidate = first_parts[0]
        if all(path.parts[0] == candidate for path in normalized_paths if len(path.parts) > 1):
            return candidate

    return normalized_paths[0].stem or fallback_name


def materialize_uploaded_dataset_files(files: List[UploadFile], relative_paths: List[str], destination_dir: Path) -> None:
    if not files:
        raise RuntimeError("请至少选择一个数据集文件。")
    if len(files) != len(relative_paths):
        raise RuntimeError("上传的数据集文件与路径数量不一致。")

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_root = destination_dir.resolve()
    for file, raw_relative_path in zip(files, relative_paths):
        relative_path = normalize_uploaded_dataset_relative_path(raw_relative_path)
        target_path = (destination_dir / relative_path).resolve()
        try:
            target_path.relative_to(destination_root)
        except ValueError as exc:
            raise RuntimeError("上传的数据集包含越界路径。") from exc
        save_uploaded_file(file, target_path)


def import_annotation_dataset_from_source_root(
    dataset_name: str,
    source_root: Path,
    current_user: Dict[str, object],
    is_public: bool,
) -> str:
    dataset_key = safe_annotation_dataset_name(dataset_name)
    structure = get_annotation_dataset_structure(dataset_key)
    existing_owner = auth_store.get_dataset_owner(dataset_key)
    if existing_owner or structure["dataset_dir"].exists():
        raise_dataset_name_unavailable()

    classes = read_uploaded_dataset_classes(source_root)
    try:
        _, target_structure = ensure_annotation_dataset_structure(dataset_key, classes)

        for relative_dir in (
            Path("images/raw"),
            Path("labels/raw"),
            Path("images/train"),
            Path("labels/train"),
            Path("images/val"),
            Path("labels/val"),
        ):
            copy_directory_contents(source_root / relative_dir, target_structure["dataset_dir"] / relative_dir)

        source_images_root = source_root / "images"
        source_labels_root = source_root / "labels"
        if source_images_root.exists() and source_labels_root.exists():
            has_nested_structure = any(
                (source_images_root / part).exists() or (source_labels_root / part).exists()
                for part in ("raw", "train", "val")
            )
            if not has_nested_structure:
                copy_directory_contents(source_images_root, target_structure["images_raw"])
                copy_directory_contents(source_labels_root, target_structure["labels_raw"])

        source_pair_count = count_available_source_pairs(target_structure)
        train_pair_count = len(collect_image_label_pairs(target_structure["images_train"], target_structure["labels_train"]))
        val_pair_count = len(collect_image_label_pairs(target_structure["images_val"], target_structure["labels_val"]))
        if source_pair_count <= 0 and train_pair_count <= 0 and val_pair_count <= 0:
            raise RuntimeError("导入后的数据集没有找到任何可用的图片标签对。")

        auth_store.ensure_dataset_access_entry(
            dataset_key,
            int(current_user["id"]),
            is_public=is_public,
            overwrite_existing=True,
        )
        return dataset_key
    except Exception:
        shutil.rmtree(structure["dataset_dir"], ignore_errors=True)
        auth_store.delete_dataset_owner(dataset_key)
        raise


def import_annotation_dataset_archive(
    dataset_name: str,
    archive_file: UploadFile,
    current_user: Dict[str, object],
    is_public: bool,
) -> str:
    desired_name = dataset_name or Path(archive_file.filename or "").stem
    temp_prefix_key = safe_annotation_dataset_name(desired_name)
    with tempfile.TemporaryDirectory(prefix=f"dataset_import_{temp_prefix_key}_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / "dataset.zip"
        extract_root = temp_dir / "extract"
        save_uploaded_file(archive_file, archive_path)
        extract_zip_archive_safely(archive_path, extract_root)
        source_root = resolve_uploaded_dataset_source_root(extract_root)
        return import_annotation_dataset_from_source_root(desired_name, source_root, current_user, is_public)


def build_admin_console_response(current_user: Dict[str, object], message: str = "管理员总控已就绪") -> AdminConsoleResponse:
    active_augment_path = get_active_augmentation_script_path()
    builtin_augment_path = get_builtin_augmentation_script_path()
    builtin_item = build_builtin_augmentation_item(builtin_augment_path)
    sync_model_registry()
    model_records_by_name = {item["model_name"]: item for item in auth_store.list_all_models()}
    dataset_records = auth_store.list_all_datasets()
    available_models = get_release_visible_model_names(model_service.available_models())
    current_model = model_service.current_model_name if model_service.current_model_name in available_models else (available_models[0] if available_models else None)
    return AdminConsoleResponse(
        success=True,
        message=message,
        data=AdminConsoleData(
            current_user=build_user_profile(current_user),
            current_model=current_model,
            available_models=available_models,
            managed_models=list_managed_models(available_models, current_model, model_records_by_name),
            managed_datasets=[build_managed_dataset_item(item, current_user) for item in dataset_records],
            builtin_augmentation_script=builtin_augment_path.name if builtin_augment_path.exists() else builtin_augment_path.name,
            active_augmentation_script=active_augment_path.name if active_augment_path else None,
            builtin_augmentation_item=builtin_item,
            managed_augmentation_scripts=list_managed_augmentation_scripts(),
        ),
    )


def build_users_response(current_user: Dict[str, object], message: str = "用户列表已就绪") -> UsersResponse:
    users = [build_user_profile(item) for item in auth_store.list_users()]
    return UsersResponse(
        success=True,
        message=message,
        data=UsersData(current_user=build_user_profile(current_user), users=users),
    )


def remove_model_files(model_name: str) -> None:
    model_path = Path(settings.models_dir) / model_name
    for candidate in (
        model_path,
        model_path.with_suffix(".labels.json"),
        model_path.with_suffix(".meta.json"),
    ):
        if candidate.exists():
            candidate.unlink()


def refresh_active_model_after_mutation(preferred_model_name: Optional[str] = None) -> Optional[str]:
    for cache in (
        model_service.sessions,
        model_service.model_errors,
        model_service.class_name_cache,
        model_service.input_size_cache,
    ):
        if preferred_model_name:
            cache.pop(preferred_model_name, None)

    available_models = model_service.available_models()
    candidate_order: List[str] = []
    if preferred_model_name and preferred_model_name in available_models:
        candidate_order.append(preferred_model_name)
    if model_service.current_model_name and model_service.current_model_name in available_models and model_service.current_model_name not in candidate_order:
        candidate_order.append(model_service.current_model_name)
    candidate_order.extend([name for name in available_models if name not in candidate_order])

    for candidate in candidate_order:
        try:
            model_service.set_active_model(candidate)
            return candidate
        except RuntimeError:
            continue

    model_service.current_model_name = None
    model_service.load_error = f"当前没有可用的 ONNX 模型：{settings.models_dir}"
    return None


def delete_model_asset(model_name: str, current_user: Dict[str, object]) -> str:
    sync_model_registry()
    normalized_name = Path(model_name or "").name
    if not normalized_name:
        raise RuntimeError("模型名称不能为空。")

    model_owner = auth_store.get_model_owner(normalized_name)
    if not model_owner:
        raise RuntimeError(f"模型不存在：{normalized_name}")
    if not can_manage_model(model_owner, current_user):
        raise RuntimeError(f"你没有权限删除模型：{normalized_name}")

    remove_model_files(normalized_name)
    auth_store.delete_model_owner(normalized_name)
    model_service.sessions.pop(normalized_name, None)
    model_service.model_errors.pop(normalized_name, None)
    model_service.class_name_cache.pop(normalized_name, None)
    model_service.input_size_cache.pop(normalized_name, None)
    if model_service.current_model_name == normalized_name:
        model_service.current_model_name = None
    refresh_active_model_after_mutation()
    return normalized_name


def upload_model_asset(
    current_user: Dict[str, object],
    model_file: UploadFile,
    labels_file: Optional[UploadFile] = None,
    metadata_file: Optional[UploadFile] = None,
    activate: bool = False,
    is_public: bool = False,
) -> Tuple[str, bool, Optional[str]]:
    model_filename = Path(model_file.filename or "").name
    if not model_filename.lower().endswith(".onnx"):
        raise HTTPException(status_code=400, detail="模型文件必须是 .onnx 格式。")

    if labels_file and getattr(labels_file, "filename", "") and not str(labels_file.filename).lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="标签文件必须是 .json 格式。")
    if metadata_file and getattr(metadata_file, "filename", "") and not str(metadata_file.filename).lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="模型说明文件必须是 .json 格式。")

    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    desired_stem = safe_model_stem(Path(model_filename).stem, "uploaded_model")
    _, onnx_path, labels_path, metadata_path = resolve_unique_model_targets(models_dir, desired_stem)

    try:
        save_uploaded_file(model_file, onnx_path)
        if labels_file and getattr(labels_file, "filename", ""):
            save_uploaded_file(labels_file, labels_path)
        if metadata_file and getattr(metadata_file, "filename", ""):
            save_uploaded_file(metadata_file, metadata_path)
    except Exception:
        for path in (onnx_path, labels_path, metadata_path):
            path.unlink(missing_ok=True)
        raise

    auth_store.ensure_model_owner(onnx_path.name, int(current_user["id"]), is_public=is_public, overwrite_existing=True)

    activated = False
    activation_error: Optional[str] = None
    if activate or not model_service.current_model_name:
        try:
            model_service.set_active_model(onnx_path.name)
            activated = True
        except RuntimeError as exc:
            activation_error = str(exc)

    return onnx_path.name, activated, activation_error


def delete_user_assets_and_record(user_id: int) -> Dict[str, int]:
    owned_datasets = auth_store.list_datasets_owned_by_user(user_id)
    owned_models = auth_store.list_models_owned_by_user(user_id)

    removed_dataset_count = 0
    removed_model_count = 0
    for item in owned_datasets:
        dataset_name = str(item.get("dataset_name") or "")
        if not dataset_name:
            continue
        structure = get_annotation_dataset_structure(dataset_name)
        if structure["dataset_dir"].exists():
            shutil.rmtree(structure["dataset_dir"], ignore_errors=True)
        removed_dataset_count += 1

    for item in owned_models:
        model_name = str(item.get("model_name") or "")
        if not model_name:
            continue
        remove_model_files(model_name)
        model_service.sessions.pop(model_name, None)
        model_service.model_errors.pop(model_name, None)
        model_service.class_name_cache.pop(model_name, None)
        model_service.input_size_cache.pop(model_name, None)
        if model_service.current_model_name == model_name:
            model_service.current_model_name = None
        removed_model_count += 1

    auth_store.delete_user(user_id)
    refresh_active_model_after_mutation()
    return {
        "dataset_count": removed_dataset_count,
        "model_count": removed_model_count,
    }


def remove_temp_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        if path.exists():
            path.unlink()


def create_zip_archive(prefix: str, members: List[Tuple[Path, Path]]) -> Path:
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".zip", delete=False) as temp_file:
        archive_path = Path(temp_file.name)

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path, archive_member in members:
            if not source_path.exists():
                continue

            archive_member_path = Path(archive_member)
            if source_path.is_dir():
                root_name = archive_member_path.as_posix().rstrip("/")
                archive.writestr(f"{root_name}/", "")
                for child in sorted(source_path.rglob("*")):
                    child_archive_path = (archive_member_path / child.relative_to(source_path)).as_posix()
                    if child.is_dir():
                        archive.writestr(f"{child_archive_path.rstrip('/')}/", "")
                    else:
                        archive.write(child, child_archive_path)
            else:
                archive.write(source_path, archive_member_path.as_posix())

    return archive_path


def parse_optional_float(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_training_metrics(run_dir: Path) -> Dict[str, Optional[float]]:
    results_path = run_dir / "results.csv"
    if not results_path.exists():
        return {
            "precision": None,
            "recall": None,
            "map50": None,
            "map50_95": None,
        }

    try:
        with results_path.open("r", encoding="utf-8", newline="") as handle:
            rows = [row for row in csv.DictReader(handle) if row]
    except Exception:
        return {
            "precision": None,
            "recall": None,
            "map50": None,
            "map50_95": None,
        }

    if not rows:
        return {
            "precision": None,
            "recall": None,
            "map50": None,
            "map50_95": None,
        }

    last_row = rows[-1]
    return {
        "precision": parse_optional_float(last_row.get("metrics/precision(B)")),
        "recall": parse_optional_float(last_row.get("metrics/recall(B)")),
        "map50": parse_optional_float(last_row.get("metrics/mAP50(B)")),
        "map50_95": parse_optional_float(last_row.get("metrics/mAP50-95(B)")),
    }


def build_training_quality_advice(metrics: Dict[str, Optional[float]]) -> Tuple[str, List[str]]:
    map50 = metrics.get("map50")
    map50_95 = metrics.get("map50_95")
    precision = metrics.get("precision")
    recall = metrics.get("recall")

    if map50 is None:
        return (
            "训练已完成，但暂时没有读到可用的验证指标，建议先用几张真实图片做预测验证。",
            [
                "确认训练运行目录下已生成 results.csv，并检查验证集是否正常参与训练。",
                "优先用几张未参与训练的真实图片做预测，观察检测框和类别是否稳定。",
            ],
        )

    if map50 >= 0.9:
        summary = "当前模型的 mAP50 很高，整体检测效果已经比较理想。"
        advice = [
            "可以先用几张真实业务图片做抽检，确认没有明显过拟合。",
            "如果线上场景复杂，可继续补充边缘样本后再做一次训练对比。",
        ]
    elif map50 >= 0.75:
        summary = "当前模型的 mAP50 表现较好，已经具备较强可用性。"
        advice = [
            "建议增加一些复杂背景、遮挡或低光照图片，进一步提升泛化能力。",
            "如果误检偏多，优先检查标签质量和相似类别是否容易混淆。",
        ]
    elif map50 >= 0.5:
        summary = "当前模型有一定识别能力，但还有明显提升空间。"
        advice = [
            "优先补充更多高质量标注样本，尤其是容易误判的类别。",
            "可以尝试增加训练轮数，或提升输入尺寸后再训练一轮对比。",
        ]
    else:
        summary = "当前模型的 mAP50 偏低，暂时不建议直接投入正式使用。"
        advice = [
            "先检查数据集标注是否准确、类别是否均衡，以及训练/验证集划分是否合理。",
            "建议补充样本数量、清理错误标签，并在更高 imgsz 或更多 epochs 下重新训练。",
        ]

    if precision is not None and recall is not None and precision - recall > 0.15:
        advice.append("当前 precision 明显高于 recall，说明漏检可能偏多，建议补充更多目标形态样本。")
    elif precision is not None and recall is not None and recall - precision > 0.15:
        advice.append("当前 recall 明显高于 precision，说明误检可能偏多，建议进一步清理标签并提高样本区分度。")

    if map50_95 is not None and map50 is not None and (map50 - map50_95) > 0.25:
        advice.append("mAP50 与 mAP50-95 差距较大，说明框定位精度还有提升空间，可尝试提高输入尺寸或优化标注框。")

    return summary, advice


def list_images(img_dir: Path) -> List[Path]:
    if not img_dir.exists():
        return []
    return sorted(p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS)


def count_raw_source_images(structure: Dict[str, Path]) -> int:
    return len(list_images(structure["images_raw"]))


def count_annotated_source_images(structure: Dict[str, Path]) -> int:
    return len(collect_image_label_pairs(structure["images_raw"], structure["labels_raw"]))


def read_annotation_boxes(label_path: Path, classes: List[str], width: int, height: int) -> List[AnnotationBoxItem]:
    if not label_path.exists() or width <= 0 or height <= 0:
        return []

    annotations: List[AnnotationBoxItem] = []
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split()
        if len(parts) != 5:
            continue

        try:
            class_index = int(parts[0])
            center_x = float(parts[1]) * width
            center_y = float(parts[2]) * height
            box_width = float(parts[3]) * width
            box_height = float(parts[4]) * height
        except (TypeError, ValueError):
            continue

        if class_index < 0 or class_index >= len(classes):
            continue

        x1 = max(0.0, center_x - (box_width / 2.0))
        y1 = max(0.0, center_y - (box_height / 2.0))
        x2 = min(float(width), center_x + (box_width / 2.0))
        y2 = min(float(height), center_y + (box_height / 2.0))
        annotations.append(
            AnnotationBoxItem(
                label=classes[class_index],
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                source="manual",
            )
        )

    return annotations


def build_annotation_source_image_items(structure: Dict[str, Path]) -> List[AnnotationSourceImageItem]:
    items: List[AnnotationSourceImageItem] = []
    for image_path in list_images(structure["images_raw"]):
        label_path = structure["labels_raw"] / f"{image_path.stem}.txt"
        annotation_count = 0
        if label_path.exists():
            annotation_count = len([line for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()])
        updated_at = datetime.fromtimestamp(image_path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        items.append(
            AnnotationSourceImageItem(
                name=image_path.name,
                has_annotation=label_path.exists(),
                annotation_count=annotation_count,
                size_bytes=int(image_path.stat().st_size or 0),
                updated_at=updated_at,
            )
        )
    return items


def collect_image_label_pairs(images_dir: Path, labels_dir: Path) -> List[Tuple[Path, Path]]:
    pairs: List[Tuple[Path, Path]] = []
    for image_path in list_images(images_dir):
        label_path = labels_dir / f"{image_path.stem}.txt"
        if label_path.exists():
            pairs.append((image_path, label_path))
    return pairs


def write_train_val_pairs(
    pairs: List[Tuple[Path, Path]],
    structure: Dict[str, Path],
    train_ratio: float,
    seed: int,
    duplicate_single_to_val: bool = False,
) -> Tuple[int, int]:
    if not pairs:
        raise HTTPException(status_code=400, detail="当前没有可用于划分 train/val 的图片与标签配对数据。")

    clear_directory(structure["images_train"])
    clear_directory(structure["labels_train"])
    clear_directory(structure["images_val"])
    clear_directory(structure["labels_val"])

    ordered_pairs = list(pairs)
    random.Random(seed).shuffle(ordered_pairs)

    if len(ordered_pairs) == 1:
        train_pairs = [ordered_pairs[0]]
        val_pairs = [ordered_pairs[0]] if duplicate_single_to_val else []
    else:
        tentative = int(len(ordered_pairs) * train_ratio)
        train_count = min(max(tentative, 1), len(ordered_pairs) - 1)
        train_pairs = ordered_pairs[:train_count]
        val_pairs = ordered_pairs[train_count:]

    for image_path, label_path in train_pairs:
        shutil.copy2(image_path, structure["images_train"] / image_path.name)
        shutil.copy2(label_path, structure["labels_train"] / label_path.name)

    for image_path, label_path in val_pairs:
        shutil.copy2(image_path, structure["images_val"] / image_path.name)
        shutil.copy2(label_path, structure["labels_val"] / label_path.name)

    return len(train_pairs), len(val_pairs)


def count_available_source_pairs(structure: Dict[str, Path]) -> int:
    raw_pairs = collect_image_label_pairs(structure["images_raw"], structure["labels_raw"])
    if raw_pairs:
        return len(raw_pairs)
    return len(collect_image_label_pairs(structure["images_train"], structure["labels_train"]))


def seed_raw_dataset_if_needed(structure: Dict[str, Path]) -> List[Tuple[Path, Path]]:
    raw_pairs = collect_image_label_pairs(structure["images_raw"], structure["labels_raw"])
    if raw_pairs:
        return raw_pairs

    train_pairs = collect_image_label_pairs(structure["images_train"], structure["labels_train"])
    if train_pairs:
        for image_path, label_path in train_pairs:
            shutil.copy2(image_path, structure["images_raw"] / image_path.name)
            shutil.copy2(label_path, structure["labels_raw"] / label_path.name)
        return collect_image_label_pairs(structure["images_raw"], structure["labels_raw"])

    val_pairs = collect_image_label_pairs(structure["images_val"], structure["labels_val"])
    if val_pairs:
        for image_path, label_path in val_pairs:
            shutil.copy2(image_path, structure["images_raw"] / image_path.name)
            shutil.copy2(label_path, structure["labels_raw"] / label_path.name)
        return collect_image_label_pairs(structure["images_raw"], structure["labels_raw"])

    return []


def run_augment_script(dataset_name: str, structure: Dict[str, Path], copies: int, seed: int) -> Tuple[List[Tuple[Path, Path]], int, Path]:
    raw_pairs = seed_raw_dataset_if_needed(structure)
    if not raw_pairs:
        raise HTTPException(status_code=400, detail=f"数据集“{dataset_name}”没有可用于增强的原始图片。")

    script_path = get_active_augmentation_script_path()
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"增强脚本不存在：{script_path}")

    temp_root = Path(tempfile.mkdtemp(prefix=f"augment_{dataset_name}_", dir=str(structure["dataset_dir"])))
    temp_images = temp_root / "images"
    temp_labels = temp_root / "labels"
    temp_images.mkdir(parents=True, exist_ok=True)
    temp_labels.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(script_path),
        "--images", str(structure["images_raw"]),
        "--labels", str(structure["labels_raw"]),
        "--out-images", str(temp_images),
        "--out-labels", str(temp_labels),
        "--copies", str(max(1, copies)),
        "--seed", str(seed),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.rmtree(temp_root, ignore_errors=True)
        detail = (result.stderr or result.stdout or "增强脚本执行失败。").strip()
        raise HTTPException(status_code=500, detail=detail)

    augmented_pairs = collect_image_label_pairs(temp_images, temp_labels)
    return augmented_pairs, len(raw_pairs), temp_root


def rebuild_train_val_split(
    dataset_name: str,
    current_user: Dict[str, object],
    train_ratio: float,
    seed: int,
    copies: int,
) -> AnnotationAugmentData:
    dataset_key, classes, structure = load_annotation_classes(dataset_name, current_user, require_write=True)
    ensure_annotation_dataset_structure(dataset_key, classes)
    raw_pairs = seed_raw_dataset_if_needed(structure)
    if not raw_pairs:
        raise HTTPException(status_code=400, detail=f"数据集“{dataset_key}”没有可用于划分的数据源图片。")

    augmented_pairs, source_count, temp_root = run_augment_script(dataset_key, structure, copies, seed)
    try:
        all_pairs = list(raw_pairs) + list(augmented_pairs)
        if not all_pairs:
            raise HTTPException(status_code=400, detail=f"数据集“{dataset_key}”没有生成任何有效的图片与标签配对数据。")

        clear_directory(structure["images_train"])
        clear_directory(structure["labels_train"])
        clear_directory(structure["images_val"])
        clear_directory(structure["labels_val"])

        rng = random.Random(seed)
        rng.shuffle(all_pairs)
        if len(all_pairs) == 1:
            train_count = 1
        else:
            tentative = int(len(all_pairs) * train_ratio)
            train_count = min(max(tentative, 1), len(all_pairs) - 1)
        val_count = len(all_pairs) - train_count

        for index, (image_path, label_path) in enumerate(all_pairs):
            target_images = structure["images_train"] if index < train_count else structure["images_val"]
            target_labels = structure["labels_train"] if index < train_count else structure["labels_val"]
            shutil.copy2(image_path, target_images / image_path.name)
            shutil.copy2(label_path, target_labels / label_path.name)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    ensure_annotation_dataset_structure(dataset_key, classes)
    return AnnotationAugmentData(
        dataset_name=dataset_key,
        source_count=source_count,
        augmented_count=len(augmented_pairs),
        total_count=len(all_pairs),
        train_count=train_count,
        val_count=val_count,
        raw_images_dir=str(structure["images_raw"]),
        train_images_dir=str(structure["images_train"]),
        val_images_dir=str(structure["images_val"]),
    )


def ensure_training_split(
    dataset_name: str,
    current_user: Dict[str, object],
    train_ratio: float,
    seed: int,
) -> Tuple[str, List[str], Dict[str, Path], int, int, Optional[Path]]:
    dataset_key, classes, structure = load_annotation_classes(dataset_name, current_user)
    dataset_owner = auth_store.get_dataset_owner(dataset_key)
    can_write_current_dataset = can_write_dataset(dataset_owner, current_user)
    if can_write_current_dataset:
        ensure_annotation_dataset_structure(dataset_key, classes)

    raw_pairs = seed_raw_dataset_if_needed(structure)
    if not raw_pairs:
        raise HTTPException(status_code=400, detail=f"数据集“{dataset_key}”没有可用于训练的源图片。")

    train_pairs = collect_image_label_pairs(structure["images_train"], structure["labels_train"])
    val_pairs = collect_image_label_pairs(structure["images_val"], structure["labels_val"])
    if train_pairs and val_pairs:
        return dataset_key, classes, structure, len(train_pairs), len(val_pairs), None

    existing_pairs = train_pairs + val_pairs
    source_pairs = raw_pairs if raw_pairs else existing_pairs
    if can_write_current_dataset:
        train_count, val_count = write_train_val_pairs(
            source_pairs,
            structure,
            train_ratio=train_ratio,
            seed=seed,
            duplicate_single_to_val=True,
        )
        return dataset_key, classes, structure, train_count, val_count, None

    temp_root = Path(tempfile.mkdtemp(prefix=f"train_{dataset_key}_"))
    _, temp_structure = ensure_annotation_dataset_structure_at(dataset_key, temp_root / dataset_key, classes)
    train_count, val_count = write_train_val_pairs(
        source_pairs,
        temp_structure,
        train_ratio=train_ratio,
        seed=seed,
        duplicate_single_to_val=True,
    )
    return dataset_key, classes, temp_structure, train_count, val_count, temp_root


def train_model_and_export(
    dataset_name: str,
    base_model: str,
    requested_model_name: Optional[str],
    epochs: int,
    imgsz: int,
    current_user: Dict[str, object],
    progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
) -> ModelTrainData:
    dataset_key, classes, structure, train_count, val_count, temp_training_root = ensure_training_split(
        dataset_name,
        current_user,
        train_ratio=settings.augment_train_ratio,
        seed=settings.augment_seed,
    )

    train_script = Path(settings.train_script_path)
    if not train_script.exists():
        raise HTTPException(status_code=500, detail=f"训练脚本不存在：{train_script}")

    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    desired_stem = safe_model_stem(requested_model_name, f"{dataset_key}_{stamp}")
    model_stem, onnx_path, labels_path, metadata_path = resolve_unique_model_targets(models_dir, desired_stem)

    training_runs_dir = Path(settings.training_runs_dir)
    training_runs_dir.mkdir(parents=True, exist_ok=True)
    run_name = f"{model_stem}_run"

    command = [
        settings.training_python_path,
        str(train_script),
        "--dataset",
        str(structure["dataset_dir"] / "dataset.yaml"),
        "--classes-file",
        str(structure["dataset_dir"] / "classes.txt"),
        "--dataset-name",
        dataset_key,
        "--base-model",
        base_model,
        "--epochs",
        str(epochs),
        "--imgsz",
        str(imgsz),
        "--workers",
        str(settings.training_workers),
        "--patience",
        str(settings.training_patience),
        "--project",
        str(training_runs_dir),
        "--name",
        run_name,
        "--output-model",
        str(onnx_path),
        "--labels-output",
        str(labels_path),
        "--metadata-output",
        str(metadata_path),
    ]
    if settings.training_device.strip():
        command.extend(["--device", settings.training_device.strip()])

    try:
        run_training_command(command, progress_callback=progress_callback)

        if not onnx_path.exists() or onnx_path.stat().st_size == 0:
            raise HTTPException(status_code=500, detail=f"训练已结束，但没有生成 ONNX 文件：{onnx_path}")

        if not labels_path.exists():
            labels_path.write_text(json.dumps(classes, ensure_ascii=False, indent=2), encoding="utf-8")

        metadata: Dict[str, object] = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {}

        run_dir = Path(str(metadata.get("run_dir") or (training_runs_dir / run_name)))
        metrics = read_training_metrics(run_dir)
        training_summary, training_advice = build_training_quality_advice(metrics)

        auth_store.ensure_model_owner(
            onnx_path.name,
            int(current_user["id"]),
            is_public=user_is_admin(current_user),
            overwrite_existing=True,
        )

        try:
            if user_is_admin(current_user):
                current_model = model_service.set_active_model(onnx_path.name)
            else:
                current_model = model_service.ensure_model_ready(onnx_path.name)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return ModelTrainData(
            dataset_name=dataset_key,
            model_name=onnx_path.name,
            base_model=base_model,
            epochs=epochs,
            imgsz=imgsz,
            train_count=train_count,
            val_count=val_count,
            classes=classes,
            onnx_path=str(onnx_path),
            labels_path=str(labels_path),
            run_dir=str(run_dir),
            precision=metrics.get("precision"),
            recall=metrics.get("recall"),
            map50=metrics.get("map50"),
            map50_95=metrics.get("map50_95"),
            training_summary=training_summary,
            training_advice=training_advice,
            current_model=current_model,
            available_models=list_accessible_model_names(current_user),
        )
    finally:
        if temp_training_root:
            shutil.rmtree(temp_training_root, ignore_errors=True)


def build_health_response(current_user: Optional[Dict[str, object]] = None) -> HealthResponse:
    sync_model_registry()
    service_available_models = get_release_visible_model_names(model_service.available_models())
    service_current_model = model_service.current_model_name if model_service.current_model_name in service_available_models else (service_available_models[0] if service_available_models else None)

    if current_user:
        available_models = list_accessible_model_names(current_user)
        current_model = get_preferred_model_name_for_user(current_user, available_models)
        model_error = None
        if not available_models:
            model_error = "当前没有你可访问的模型，请联系管理员上传公开模型或使用你自己的模型。"
        elif current_model:
            model_error = model_service.model_errors.get(current_model)
            if current_model == service_current_model:
                model_error = model_service.load_error or model_error
        model_loaded = bool(current_model and current_model in model_service.sessions)
        if current_model == service_current_model:
            model_loaded = model_service.is_ready
    else:
        available_models = service_available_models
        current_model = service_current_model
        model_loaded = model_service.is_ready
        model_error = model_service.load_error

    return HealthResponse(
        success=True,
        message="服务可用",
        data=HealthData(
            status="正常",
            model_loaded=model_loaded,
            model_error=model_error,
            current_model=current_model,
            available_models=available_models,
        ),
    )


def build_models_response(current_user: Dict[str, object], message: str = "模型列表已就绪") -> ModelsResponse:
    accessible_models = list_accessible_model_names(current_user)
    current_model = get_preferred_model_name_for_user(current_user, accessible_models)
    return ModelsResponse(
        success=True,
        message=message,
        data=ModelsData(
            current_model=current_model,
            available_models=accessible_models,
            available_model_items=[build_model_access_item(model_name, current_user) for model_name in accessible_models],
        ),
    )


def resolve_unique_annotation_source_image_path(structure: Dict[str, Path], original_filename: str) -> Path:
    safe_name = Path(original_filename or "").name
    extension = Path(safe_name).suffix.lower()
    if extension not in IMG_EXTS:
        extension = ".jpg"
    stem = safe_annotation_stem(safe_name or "annotation_image")
    image_path = structure["images_raw"] / f"{stem}{extension}"
    counter = 1
    while image_path.exists():
        image_path = structure["images_raw"] / f"{stem}_{counter}{extension}"
        counter += 1
    return image_path


async def import_annotation_source_images(
    files: List[UploadFile],
    dataset_name: Optional[str],
    current_user: Dict[str, object],
) -> Tuple[str, int]:
    dataset_key, classes, structure = load_annotation_classes(dataset_name, current_user, require_write=True)
    ensure_annotation_dataset_structure(dataset_key, classes)

    imported_count = 0
    for file in files:
        ensure_supported_uploaded_image(file)
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail=f"上传的图片为空：{Path(file.filename or '').name or '未命名图片'}")
        try:
            image = Image.open(BytesIO(image_bytes))
            image.load()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"上传的图片无效：{Path(file.filename or '').name or '未命名图片'}") from exc

        image_path = resolve_unique_annotation_source_image_path(structure, file.filename or "annotation_image.jpg")
        extension = image_path.suffix.lower()
        if extension in {".jpg", ".jpeg"}:
            image.convert("RGB").save(image_path, format="JPEG", quality=95)
        elif extension == ".png":
            image.save(image_path, format="PNG")
        elif extension == ".bmp":
            image.save(image_path, format="BMP")
        elif extension in {".tif", ".tiff"}:
            image.save(image_path, format="TIFF")
        else:
            image.save(image_path, format="WEBP", quality=95)
        imported_count += 1

    return dataset_key, imported_count


def parse_annotation_items(raw_annotations: str) -> List[dict]:
    try:
        payload = json.loads(raw_annotations)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="标注数据必须是合法的 JSON。") from exc

    if not isinstance(payload, list) or not payload:
        raise HTTPException(status_code=400, detail="至少需要一个标注框。")

    parsed: List[dict] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"第 {index + 1} 个标注项必须是对象。")

        label = str(item.get("label") or "").strip()
        if not label:
            raise HTTPException(status_code=400, detail=f"第 {index + 1} 个标注项缺少类别名称。")

        try:
            x1 = float(item.get("x1"))
            y1 = float(item.get("y1"))
            x2 = float(item.get("x2"))
            y2 = float(item.get("y2"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"第 {index + 1} 个标注项包含无效坐标。") from exc

        parsed.append({
            "label": label,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "source": str(item.get("source") or "manual"),
        })

    return parsed


def save_annotation_files(
    filename: str,
    image_bytes: bytes,
    annotations: List[dict],
    dataset_name: Optional[str],
    current_user: Dict[str, object],
    source_filename: Optional[str] = None,
) -> AnnotationSaveData:
    dataset_key, classes, structure = load_annotation_classes(dataset_name, current_user, require_write=True)
    class_to_index = {label: index for index, label in enumerate(classes)}

    try:
        image = Image.open(BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="上传的标注图片无效。") from exc

    width, height = image.size
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="上传的标注图片尺寸无效。")

    extension = Path(filename or "annotation_image.jpg").suffix.lower()
    if source_filename:
        source_basename = Path(source_filename).name
        if not source_basename:
            raise HTTPException(status_code=400, detail="待覆盖的原始图片文件名无效。")
        extension = Path(source_basename).suffix.lower() or extension
        raw_image_path = structure["images_raw"] / source_basename
        raw_label_path = structure["labels_raw"] / f"{Path(source_basename).stem}.txt"

    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
        extension = ".jpg"

    if not source_filename:
        stem = safe_annotation_stem(filename)
        raw_image_path = structure["images_raw"] / f"{stem}{extension}"
        raw_label_path = structure["labels_raw"] / f"{stem}.txt"

        counter = 1
        while raw_image_path.exists() or raw_label_path.exists():
            raw_image_path = structure["images_raw"] / f"{stem}_{counter}{extension}"
            raw_label_path = structure["labels_raw"] / f"{stem}_{counter}.txt"
            counter += 1

    yolo_lines: List[str] = []
    saved_classes: List[str] = []
    for index, annotation in enumerate(annotations):
        label = annotation["label"]
        if label not in class_to_index:
            raise HTTPException(status_code=400, detail=f"当前数据集（{dataset_key}）中不存在该标注类别：{label}")

        left = max(0.0, min(annotation["x1"], annotation["x2"]))
        top = max(0.0, min(annotation["y1"], annotation["y2"]))
        right = min(float(width), max(annotation["x1"], annotation["x2"]))
        bottom = min(float(height), max(annotation["y1"], annotation["y2"]))

        if right - left < 2 or bottom - top < 2:
            raise HTTPException(status_code=400, detail=f"第 {index + 1} 个标注框过小，无法保存。")

        center_x = ((left + right) / 2.0) / width
        center_y = ((top + bottom) / 2.0) / height
        box_width = (right - left) / width
        box_height = (bottom - top) / height
        class_index = class_to_index[label]
        yolo_lines.append(f"{class_index} {center_x:.6f} {center_y:.6f} {box_width:.6f} {box_height:.6f}")
        saved_classes.append(label)

    if extension in {".jpg", ".jpeg"}:
        image.convert("RGB").save(raw_image_path, format="JPEG", quality=95)
    elif extension == ".png":
        image.save(raw_image_path, format="PNG")
    elif extension == ".bmp":
        image.save(raw_image_path, format="BMP")
    elif extension in {".tif", ".tiff"}:
        image.save(raw_image_path, format="TIFF")
    else:
        image.save(raw_image_path, format="WEBP", quality=95)

    raw_label_path.write_text("\n".join(yolo_lines), encoding="utf-8")

    train_pairs = collect_image_label_pairs(structure["images_train"], structure["labels_train"])
    val_pairs = collect_image_label_pairs(structure["images_val"], structure["labels_val"])
    if not train_pairs and not val_pairs:
        mirror_image_path = structure["images_train"] / raw_image_path.name
        mirror_label_path = structure["labels_train"] / raw_label_path.name
        shutil.copy2(raw_image_path, mirror_image_path)
        shutil.copy2(raw_label_path, mirror_label_path)

    return AnnotationSaveData(
        dataset_name=dataset_key,
        filename=raw_image_path.name,
        image_path=str(raw_image_path),
        label_path=str(raw_label_path),
        annotation_count=len(yolo_lines),
        saved_classes=sorted(set(saved_classes)),
    )


@router.get("/", response_model=HealthResponse)
def root(current_user: Optional[Dict[str, object]] = Depends(get_optional_current_user)) -> HealthResponse:
    return build_health_response(current_user)


@router.get("/health", response_model=HealthResponse)
def health(current_user: Optional[Dict[str, object]] = Depends(get_optional_current_user)) -> HealthResponse:
    return build_health_response(current_user)


@router.post("/auth/login", response_model=AuthSessionResponse)
def auth_login(payload: AuthLoginRequest = Body(...)) -> AuthSessionResponse:
    try:
        user = auth_store.authenticate_user(payload.username, payload.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误。")
    token = auth_store.create_session(int(user["id"]))
    return AuthSessionResponse(
        success=True,
        message="登录成功",
        data=AuthSessionData(token=token, user=build_user_profile(user)),
    )


@router.post("/auth/register", response_model=AuthSessionResponse)
def auth_register(payload: AuthRegisterRequest = Body(...)) -> AuthSessionResponse:
    try:
        user = auth_store.create_user(payload.username, payload.password, role="user", display_name=payload.display_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = auth_store.create_session(int(user["id"]))
    return AuthSessionResponse(
        success=True,
        message="注册成功",
        data=AuthSessionData(token=token, user=build_user_profile(user)),
    )


@router.get("/auth/session", response_model=AuthSessionResponse)
def auth_session(current_user: Dict[str, object] = Depends(get_current_user)) -> AuthSessionResponse:
    return AuthSessionResponse(
        success=True,
        message="登录状态有效",
        data=AuthSessionData(token=None, user=build_user_profile(current_user)),
    )


@router.post("/auth/logout", response_model=AuthSessionResponse)
def auth_logout(x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token")) -> AuthSessionResponse:
    if x_auth_token:
        auth_store.delete_session(x_auth_token)
    return AuthSessionResponse(
        success=True,
        message="退出登录成功",
        data=AuthSessionData(token=None, user=None),
    )


@router.get("/users", response_model=UsersResponse)
def list_users(current_user: Dict[str, object] = Depends(require_admin)) -> UsersResponse:
    return build_users_response(current_user, message="用户列表已加载")


@router.post("/admin/users/{user_id}/disabled", response_model=UsersResponse)
def set_user_disabled(
    user_id: int,
    payload: ToggleValueRequest = Body(...),
    current_user: Dict[str, object] = Depends(require_admin),
) -> UsersResponse:
    target_user = auth_store.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")
    if int(target_user["id"]) == int(current_user["id"]):
        raise HTTPException(status_code=400, detail="不能封禁当前登录的管理员账号。")
    if str(target_user.get("role") or "") == "admin":
        raise HTTPException(status_code=400, detail="不能封禁管理员账号。")

    updated_user = auth_store.set_user_disabled(user_id, payload.value)
    if not updated_user:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")
    action = "已封禁" if payload.value else "已解除封禁"
    return build_users_response(current_user, message=f"{action}用户：{updated_user['username']}")


@router.post("/admin/users/{user_id}/flagged", response_model=UsersResponse)
def set_user_flagged(
    user_id: int,
    payload: ToggleValueRequest = Body(...),
    current_user: Dict[str, object] = Depends(require_admin),
) -> UsersResponse:
    target_user = auth_store.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")

    updated_user = auth_store.set_user_flagged(user_id, payload.value)
    if not updated_user:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")
    action = "已标记重点关注" if payload.value else "已取消重点关注"
    return build_users_response(current_user, message=f"{action}：{updated_user['username']}")


@router.delete("/admin/users/{user_id}", response_model=UsersResponse)
def delete_user(
    user_id: int,
    current_user: Dict[str, object] = Depends(require_admin),
) -> UsersResponse:
    target_user = auth_store.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail=f"用户不存在：{user_id}")
    if int(target_user["id"]) == int(current_user["id"]):
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号。")
    if str(target_user.get("role") or "") == "admin":
        raise HTTPException(status_code=400, detail="不能删除管理员账号。")

    removed = delete_user_assets_and_record(user_id)
    return build_users_response(
        current_user,
        message=f"已删除用户 {target_user['username']}，同步清理 {removed['dataset_count']} 个数据集和 {removed['model_count']} 个模型。",
    )


@router.get("/admin/console", response_model=AdminConsoleResponse)
def get_admin_console(current_user: Dict[str, object] = Depends(require_admin)) -> AdminConsoleResponse:
    return build_admin_console_response(current_user, message="管理员总控已加载")


@router.post("/models/upload", response_model=ModelsResponse)
def upload_model(
    current_user: Dict[str, object] = Depends(get_current_user),
    model_file: UploadFile = File(...),
    labels_file: Optional[UploadFile] = File(default=None),
    metadata_file: Optional[UploadFile] = File(default=None),
    activate: bool = Form(default=False),
    is_public: bool = Form(default=False),
) -> ModelsResponse:
    try:
        model_name, activated, activation_error = upload_model_asset(
            current_user=current_user,
            model_file=model_file,
            labels_file=labels_file,
            metadata_file=metadata_file,
            activate=activate,
            is_public=is_public,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    owner_label = "官方" if user_is_admin(current_user) else "用户"
    visibility_label = "公开" if is_public else "私有"
    message = f"已上传{owner_label}模型 {model_name}（{visibility_label}）"
    if activated:
        message += "，并已设为当前模型。"
    elif activation_error:
        message += f"；但自动启用失败：{activation_error}"
    return build_models_response(current_user, message=message)


@router.post("/admin/models/upload", response_model=AdminConsoleResponse)
def admin_upload_model(
    current_user: Dict[str, object] = Depends(require_admin),
    model_file: UploadFile = File(...),
    labels_file: Optional[UploadFile] = File(default=None),
    metadata_file: Optional[UploadFile] = File(default=None),
    activate: bool = Form(default=False),
    is_public: bool = Form(default=True),
) -> AdminConsoleResponse:
    try:
        model_name, activated, activation_error = upload_model_asset(
            current_user=current_user,
            model_file=model_file,
            labels_file=labels_file,
            metadata_file=metadata_file,
            activate=activate,
            is_public=is_public,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    message = f"已上传模型 {model_name}"
    message += "（公开）" if is_public else "（私有）"
    if activated:
        message += "，并已设为当前模型。"
    elif activation_error:
        message += f"；但自动启用失败：{activation_error}"

    return build_admin_console_response(current_user, message=message)


@router.post("/admin/datasets/upload", response_model=AnnotationClassesResponse)
def admin_upload_dataset(
    current_user: Dict[str, object] = Depends(require_admin),
    dataset_file: UploadFile = File(...),
    dataset_name: Optional[str] = Form(default=None),
    is_public: bool = Form(default=True),
) -> AnnotationClassesResponse:
    archive_filename = Path(dataset_file.filename or "").name
    if not archive_filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="数据集压缩包必须是 .zip 格式。")

    try:
        imported_dataset = import_annotation_dataset_archive(
            dataset_name or Path(archive_filename).stem,
            dataset_file,
            current_user,
            is_public=is_public,
        )
        visibility_text = "公开" if is_public else "私有"
        return build_annotation_classes_response(current_user, imported_dataset, message=f"已导入{visibility_text}数据集：{imported_dataset}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/augmentations/upload", response_model=AdminConsoleResponse)
def admin_upload_augmentation_script(
    current_user: Dict[str, object] = Depends(require_admin),
    script_file: UploadFile = File(...),
    activate: bool = Form(default=True),
    display_name: Optional[str] = Form(default=None),
    version: Optional[str] = Form(default=None),
    dataset_types: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    author: Optional[str] = Form(default=None),
) -> AdminConsoleResponse:
    script_filename = Path(script_file.filename or "").name
    if not script_filename.lower().endswith(".py"):
        raise HTTPException(status_code=400, detail="增强算法文件必须是 .py 脚本。")

    algorithms_dir = ensure_augmentation_algorithms_dir()
    target_path = resolve_unique_augmentation_script_target(algorithms_dir, Path(script_filename).stem or "augmentation_algorithm")
    try:
        save_uploaded_file(script_file, target_path)
        write_augmentation_metadata(
            target_path,
            {
                "display_name": display_name,
                "version": version,
                "dataset_types": parse_freeform_list(dataset_types),
                "description": description,
                "author": author or current_user.get("display_name") or current_user.get("username"),
            },
        )
    except (RuntimeError, OSError) as exc:
        target_path.unlink(missing_ok=True)
        target_path.with_suffix(".meta.json").unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if activate:
        write_active_augmentation_override(target_path.name)
        message = f"已上传增强算法 {target_path.name}，并设为当前生效脚本。"
    else:
        message = f"已上传增强算法 {target_path.name}。"

    return build_admin_console_response(current_user, message=message)


@router.post("/admin/augmentations/select", response_model=AdminConsoleResponse)
def admin_select_augmentation_script(
    script_name: Optional[str] = Query(default=None, description="上传后的增强算法脚本文件名，留空则切回内置脚本"),
    current_user: Dict[str, object] = Depends(require_admin),
) -> AdminConsoleResponse:
    normalized_name = Path(script_name or "").name
    if not normalized_name:
        clear_active_augmentation_override()
        return build_admin_console_response(current_user, message="已切回内置增强算法。")

    script_path = ensure_augmentation_algorithms_dir() / normalized_name
    if not script_path.exists() or script_path.suffix.lower() != ".py":
        raise HTTPException(status_code=404, detail=f"增强算法脚本不存在：{normalized_name}")

    write_active_augmentation_override(normalized_name)
    return build_admin_console_response(current_user, message=f"已切换当前增强算法：{normalized_name}")


@router.get("/models", response_model=ModelsResponse)
def list_models(current_user: Dict[str, object] = Depends(get_current_user)) -> ModelsResponse:
    return build_models_response(current_user)


@router.get("/models/{model_name}/download")
def download_model(
    model_name: str,
    current_user: Dict[str, object] = Depends(get_current_user),
) -> FileResponse:
    accessible_model_name = ensure_model_access(model_name, current_user)

    model_path = Path(settings.models_dir) / accessible_model_name
    model_stem = Path(accessible_model_name).stem
    archive_members: List[Tuple[Path, Path]] = [
        (model_path, Path(model_stem) / model_path.name),
    ]

    labels_path = model_path.with_suffix(".labels.json")
    metadata_path = model_path.with_suffix(".meta.json")
    if labels_path.exists():
        archive_members.append((labels_path, Path(model_stem) / labels_path.name))
    if metadata_path.exists():
        archive_members.append((metadata_path, Path(model_stem) / metadata_path.name))

    archive_path = create_zip_archive("model_download_", archive_members)
    return FileResponse(
        path=str(archive_path),
        media_type="application/zip",
        filename=f"{model_stem}_model.zip",
        background=BackgroundTask(remove_temp_file, archive_path),
    )


@router.post("/models/delete", response_model=ModelsResponse)
def remove_model(
    payload: ModelDeleteRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> ModelsResponse:
    try:
        deleted_model_name = delete_model_asset(payload.model_name, current_user)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_models_response(current_user, message=f"已删除模型：{deleted_model_name}")


@router.post("/models/select", response_model=ModelsResponse)
def select_model(
    model_name: str = Query(..., description="Model filename in models directory"),
    current_user: Dict[str, object] = Depends(require_admin),
) -> ModelsResponse:
    try:
        selected_model = model_service.set_active_model(ensure_model_access(model_name, current_user))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return build_models_response(current_user, message=f"已切换当前模型：{selected_model}")


@router.post("/models/train", response_model=ModelTrainResponse)
def train_model(
    payload: ModelTrainRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> ModelTrainResponse:
    dataset_name = payload.dataset_name
    base_model = (payload.base_model or settings.training_base_model).strip()
    model_name = (payload.model_name or "").strip() or None
    epochs = payload.epochs if payload.epochs is not None else settings.training_epochs
    imgsz = payload.imgsz if payload.imgsz is not None else settings.training_imgsz

    if not dataset_name.strip():
        raise HTTPException(status_code=400, detail="训练时必须填写数据集名称。")
    if not base_model:
        raise HTTPException(status_code=400, detail="训练时必须选择基础模型。")
    if epochs < 1:
        raise HTTPException(status_code=400, detail="训练轮数至少要为 1。")
    if imgsz < 32:
        raise HTTPException(status_code=400, detail="训练图片尺寸至少要为 32。")

    data = train_model_and_export(dataset_name, base_model, model_name, epochs, imgsz, current_user)
    return ModelTrainResponse(
        success=True,
        message="模型训练并导出成功",
        data=data,
    )


@router.post("/models/train/tasks", response_model=ModelTrainTaskResponse)
def start_train_model_task(
    payload: ModelTrainRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> ModelTrainTaskResponse:
    dataset_name = payload.dataset_name
    base_model = (payload.base_model or settings.training_base_model).strip()
    model_name = (payload.model_name or "").strip() or None
    epochs = payload.epochs if payload.epochs is not None else settings.training_epochs
    imgsz = payload.imgsz if payload.imgsz is not None else settings.training_imgsz

    if not dataset_name.strip():
        raise HTTPException(status_code=400, detail="训练时必须填写数据集名称。")
    if not base_model:
        raise HTTPException(status_code=400, detail="训练时必须选择基础模型。")
    if epochs < 1:
        raise HTTPException(status_code=400, detail="训练轮数至少要为 1。")
    if imgsz < 32:
        raise HTTPException(status_code=400, detail="训练图片尺寸至少要为 32。")

    data = start_training_task(dataset_name, base_model, model_name, epochs, imgsz, current_user)
    return ModelTrainTaskResponse(
        success=True,
        message="模型训练任务已启动",
        data=data,
    )


@router.get("/models/train/tasks/{task_id}", response_model=ModelTrainTaskResponse)
def get_train_model_task(
    task_id: str,
    current_user: Dict[str, object] = Depends(get_current_user),
) -> ModelTrainTaskResponse:
    data = get_train_task_data(task_id, current_user)
    return ModelTrainTaskResponse(
        success=True,
        message="模型训练任务状态",
        data=data,
    )


@router.get("/annotation/classes", response_model=AnnotationClassesResponse)
def annotation_classes(
    dataset: Optional[str] = Query(default=None, description="Target annotation dataset name"),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationClassesResponse:
    try:
        return build_annotation_classes_response(current_user, dataset_name=dataset)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/annotation/datasets", response_model=AnnotationClassesResponse)
def create_dataset(
    payload: AnnotationDatasetCreateRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationClassesResponse:
    try:
        dataset_key = create_annotation_dataset(
            payload.dataset_name,
            current_user,
            payload.source_dataset,
            payload.is_public,
            payload.class_template_key,
        )
        return build_annotation_classes_response(current_user, dataset_key, message=f"数据集已就绪：{dataset_key}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/annotation/datasets/import-folder", response_model=AnnotationClassesResponse)
async def import_dataset_from_folder(
    current_user: Dict[str, object] = Depends(get_current_user),
    files: List[UploadFile] = File(...),
    relative_paths: List[str] = Form(...),
    dataset_name: Optional[str] = Form(default=None),
    is_public: bool = Form(default=False),
) -> AnnotationClassesResponse:
    try:
        inferred_name = dataset_name or infer_uploaded_dataset_name(relative_paths)
        with tempfile.TemporaryDirectory(prefix=f"dataset_folder_import_{safe_annotation_dataset_name(inferred_name)}_") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            upload_root = temp_dir / "upload"
            materialize_uploaded_dataset_files(files, relative_paths, upload_root)
            source_root = resolve_uploaded_dataset_source_root(upload_root)
            imported_dataset = import_annotation_dataset_from_source_root(inferred_name, source_root, current_user, is_public)
        visibility_text = "公开" if is_public else "私有"
        return build_annotation_classes_response(current_user, imported_dataset, message=f"已导入{visibility_text}数据集：{imported_dataset}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/annotation/datasets/{dataset_name}/download")
def download_annotation_dataset(
    dataset_name: str,
    current_user: Dict[str, object] = Depends(get_current_user),
) -> FileResponse:
    dataset_key = ensure_dataset_access(dataset_name, current_user, allow_auto_create=False)
    structure = get_annotation_dataset_structure(dataset_key)
    if not structure["dataset_dir"].exists():
        raise HTTPException(status_code=404, detail=f"数据集不存在：{dataset_key}")

    load_annotation_classes(dataset_key, current_user)
    archive_path = create_zip_archive(
        "dataset_download_",
        [(structure["dataset_dir"], Path(dataset_key))],
    )
    return FileResponse(
        path=str(archive_path),
        media_type="application/zip",
        filename=f"{dataset_key}_dataset.zip",
        background=BackgroundTask(remove_temp_file, archive_path),
    )


@router.post("/annotation/source-images/upload", response_model=AnnotationClassesResponse)
async def upload_annotation_source_images(
    dataset_name: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationClassesResponse:
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一张图片。")

    try:
        dataset_key, imported_count = await import_annotation_source_images(files, dataset_name, current_user)
        return build_annotation_classes_response(
            current_user,
            dataset_key,
            message=f"已导入 {imported_count} 张原始图片到数据集：{dataset_key}",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/annotation/source-images/{dataset_name}/{image_name}")
def download_annotation_source_image(
    dataset_name: str,
    image_name: str,
    current_user: Dict[str, object] = Depends(get_current_user),
) -> FileResponse:
    dataset_key = ensure_dataset_access(dataset_name, current_user, allow_auto_create=False)
    structure = get_annotation_dataset_structure(dataset_key)
    source_image_name = Path(image_name or "").name
    if not source_image_name:
        raise HTTPException(status_code=404, detail="原始图片不存在。")

    image_path = structure["images_raw"] / source_image_name
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"原始图片不存在：{source_image_name}")

    return FileResponse(path=str(image_path), filename=image_path.name)


@router.get("/annotation/source-images/{dataset_name}/{image_name}/detail", response_model=AnnotationSourceImageDetailResponse)
def get_annotation_source_image_detail(
    dataset_name: str,
    image_name: str,
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationSourceImageDetailResponse:
    dataset_key, classes, structure = load_annotation_classes(dataset_name, current_user, allow_auto_create=False)
    source_image_name = Path(image_name or "").name
    if not source_image_name:
        raise HTTPException(status_code=404, detail="原始图片不存在。")

    image_path = structure["images_raw"] / source_image_name
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"原始图片不存在：{source_image_name}")

    label_path = structure["labels_raw"] / f"{image_path.stem}.txt"
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"无法读取原始图片：{source_image_name}") from exc

    annotations = read_annotation_boxes(label_path, classes, width, height)
    return AnnotationSourceImageDetailResponse(
        success=True,
        message="原始图片标注详情已就绪",
        data=AnnotationSourceImageDetailData(
            dataset_name=dataset_key,
            image_name=image_path.name,
            has_annotation=label_path.exists(),
            annotation_count=len(annotations),
            image_path=str(image_path),
            label_path=str(label_path),
            annotations=annotations,
        ),
    )


@router.post("/annotation/datasets/delete", response_model=AnnotationClassesResponse)
def remove_dataset(
    payload: AnnotationDatasetDeleteRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationClassesResponse:
    try:
        next_dataset = delete_annotation_dataset(payload.dataset_name, current_user)
        return build_annotation_classes_response(current_user, next_dataset, message=f"数据集已删除：{safe_annotation_dataset_name(payload.dataset_name)}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/annotation/classes", response_model=AnnotationClassesResponse)
def create_annotation_class(
    payload: AnnotationClassCreateRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationClassesResponse:
    try:
        dataset_key, class_name, was_created = append_annotation_class(payload.dataset_name, current_user, payload.class_name)
        ensure_annotation_class_ai_advice(dataset_key, class_name, current_user)
        action_text = "类别已添加并写入建议库" if was_created else "类别已存在，建议库已就绪"
        return build_annotation_classes_response(current_user, dataset_key, message=f"{action_text}：{class_name}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/annotation/classes/delete", response_model=AnnotationClassesResponse)
def remove_annotation_class(
    payload: AnnotationClassDeleteRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationClassesResponse:
    try:
        dataset_key, class_name = delete_annotation_class(payload.dataset_name, current_user, payload.class_name)
        return build_annotation_classes_response(current_user, dataset_key, message=f"类别已删除：{class_name}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/annotation/augment", response_model=AnnotationAugmentResponse)
def augment_annotation_dataset(
    payload: AnnotationAugmentRequest = Body(...),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationAugmentResponse:
    dataset_name = payload.dataset_name
    copies = payload.copies if payload.copies is not None else settings.augment_copies
    train_ratio = payload.train_ratio if payload.train_ratio is not None else settings.augment_train_ratio
    seed = payload.seed if payload.seed is not None else settings.augment_seed

    if copies < 1:
        raise HTTPException(status_code=400, detail="增强份数至少要为 1。")
    if not 0.1 <= train_ratio <= 0.95:
        raise HTTPException(status_code=400, detail="训练集比例必须在 0.1 到 0.95 之间。")

    data = rebuild_train_val_split(dataset_name, current_user, train_ratio, seed, copies)
    return AnnotationAugmentResponse(
        success=True,
        message="数据集增强与划分已完成",
        data=data,
    )


@router.post("/annotation/save", response_model=AnnotationSaveResponse)
async def save_annotation(
    file: Optional[UploadFile] = File(default=None),
    annotations: str = Form(...),
    dataset_name: Optional[str] = Form(default=None),
    source_filename: Optional[str] = Form(default=None),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> AnnotationSaveResponse:
    image_bytes: bytes
    resolved_filename: str
    if file is not None:
        ensure_supported_uploaded_image(file)
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="上传的标注图片为空。")
        resolved_filename = file.filename or source_filename or "annotation_image.jpg"
    elif source_filename:
        dataset_key = ensure_dataset_write_access(dataset_name, current_user, allow_auto_create=False)
        structure = get_annotation_dataset_structure(dataset_key)
        source_image_name = Path(source_filename).name
        image_path = structure["images_raw"] / source_image_name
        if not image_path.exists() or not image_path.is_file():
            raise HTTPException(status_code=404, detail=f"原始图片不存在：{source_image_name}")
        image_bytes = image_path.read_bytes()
        resolved_filename = source_image_name
    else:
        raise HTTPException(status_code=400, detail="请上传标注图片，或指定已有原始图片。")

    annotation_items = parse_annotation_items(annotations)
    saved = save_annotation_files(
        resolved_filename,
        image_bytes,
        annotation_items,
        dataset_name,
        current_user,
        source_filename=source_filename,
    )
    return AnnotationSaveResponse(
        success=True,
        message="标注已按 YOLO 格式保存",
        data=saved,
    )


@router.post("/ai/recommendation", response_model=AiRecommendationResponse)
def get_ai_recommendation(payload: AiRecommendationRequest = Body(...)) -> AiRecommendationResponse:
    advice = generate_ai_advice(
        disease_label=payload.disease_label,
        dataset_name=payload.dataset_name,
        confidence=float(payload.confidence or 0.0),
        top_predictions=[item.model_dump() for item in payload.top_predictions],
    )
    return AiRecommendationResponse(
        success=True,
        message="智能建议已就绪",
        data=advice,
    )


@router.post("/predict", response_model=PredictResponse)
async def predict(
    file: UploadFile = File(...),
    model_name: Optional[str] = Query(default=None, description="Optional model filename override"),
    include_ai_advice: bool = Query(default=True, description="Whether to generate AI advice for this prediction"),
    confidence_threshold: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Optional confidence threshold override"),
    current_user: Dict[str, object] = Depends(get_current_user),
) -> PredictResponse:
    ensure_supported_uploaded_image(file)

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="上传的文件为空。")

    try:
        prediction_started = perf_counter()
        prediction = model_service.predict(
            image_bytes,
            model_name=resolve_predict_model_name(model_name, current_user),
            confidence_threshold=confidence_threshold,
        )
        prediction_ms = int((perf_counter() - prediction_started) * 1000)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    ai_advice = None
    advice_ms = None
    if include_ai_advice:
        advice_started = perf_counter()
        ai_advice = generate_ai_advice(
            disease_label=str(prediction.get("predicted_class") or "No detection"),
            confidence=float(prediction.get("confidence") or 0.0),
            top_predictions=list(prediction.get("top_predictions") or []),
            image_bytes=image_bytes,
            image_content_type=file.content_type,
        )
        advice_ms = int((perf_counter() - advice_started) * 1000)

    return PredictResponse(
        success=True,
        message="识别完成",
        data=PredictData(
            filename=file.filename or "unknown",
            model_name=prediction.get("model_name"),
            predicted_class=prediction["predicted_class"],
            predicted_index=prediction["predicted_index"],
            confidence=prediction["confidence"],
            top_predictions=prediction["top_predictions"],
            detections=prediction["detections"],
            ai_advice=ai_advice,
            ai_advice_included=include_ai_advice,
            prediction_ms=prediction_ms,
            advice_ms=advice_ms,
        ),
    )
