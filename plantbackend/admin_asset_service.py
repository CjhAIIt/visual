from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import shutil

try:
    from .augmentation_manager import (
        get_active_augmentation_script_path,
        list_managed_augmentation_paths,
        read_augmentation_metadata,
    )
    from .config import settings
    from .schemas import ManagedAugmentationItem, ManagedModelItem
except ImportError:
    from augmentation_manager import (
        get_active_augmentation_script_path,
        list_managed_augmentation_paths,
        read_augmentation_metadata,
    )
    from config import settings
    from schemas import ManagedAugmentationItem, ManagedModelItem


def format_file_timestamp(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def save_uploaded_file(upload, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    upload.file.seek(0)
    total_bytes = 0
    try:
        with target.open("wb") as destination:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > int(settings.max_upload_bytes):
                    raise RuntimeError(
                        f"上传文件过大，当前上限为 {int(settings.max_upload_bytes) // (1024 * 1024)} MB。"
                    )
                destination.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        upload.file.seek(0)


def list_managed_models(
    available_model_names: List[str],
    current_model_name: Optional[str],
    model_records_by_name: Optional[Dict[str, Dict[str, object]]] = None,
) -> List[ManagedModelItem]:
    models: List[ManagedModelItem] = []
    for model_name in available_model_names:
        model_path = Path(settings.models_dir) / model_name
        if not model_path.exists():
            continue
        model_record = (model_records_by_name or {}).get(model_name, {})
        models.append(
            ManagedModelItem(
                name=model_name,
                size_bytes=int(model_path.stat().st_size),
                uploaded_at=format_file_timestamp(model_path),
                has_labels=model_path.with_suffix(".labels.json").exists(),
                has_metadata=model_path.with_suffix(".meta.json").exists(),
                is_active=current_model_name == model_name,
                is_public=bool(model_record.get("is_public")),
                is_official=str(model_record.get("owner_role") or "") == "admin",
                can_manage=True,
                owner_username=str(model_record.get("owner_username")) if model_record.get("owner_username") else None,
                owner_display_name=str(model_record.get("owner_display_name")) if model_record.get("owner_display_name") else None,
            )
        )
    return models


def list_managed_augmentation_scripts() -> List[ManagedAugmentationItem]:
    active_path = get_active_augmentation_script_path()
    items: List[ManagedAugmentationItem] = []
    for script_path in list_managed_augmentation_paths():
        metadata = read_augmentation_metadata(script_path)
        items.append(
            ManagedAugmentationItem(
                name=script_path.name,
                size_bytes=int(script_path.stat().st_size),
                uploaded_at=format_file_timestamp(script_path),
                is_active=active_path.resolve() == script_path.resolve(),
                is_builtin=False,
                display_name=str(metadata.get("display_name") or script_path.stem),
                version=str(metadata.get("version") or "") or None,
                description=str(metadata.get("description") or "") or None,
                dataset_types=[str(item) for item in metadata.get("dataset_types", []) if str(item).strip()],
                author=str(metadata.get("author") or "") or None,
            )
        )
    return items


def build_builtin_augmentation_item(script_path: Path) -> ManagedAugmentationItem:
    metadata = read_augmentation_metadata(script_path)
    if not metadata.get("description"):
        metadata["description"] = "默认基础增强链路，适合快速完成通用叶片检测数据集的扩增与划分。"
    if not metadata.get("dataset_types"):
        metadata["dataset_types"] = ["通用", "叶片病害", "目标检测"]
    if not metadata.get("display_name"):
        metadata["display_name"] = "内置基础增强"
    return ManagedAugmentationItem(
        name=script_path.name,
        size_bytes=int(script_path.stat().st_size) if script_path.exists() else 0,
        uploaded_at=format_file_timestamp(script_path),
        is_active=get_active_augmentation_script_path().resolve() == script_path.resolve(),
        is_builtin=True,
        display_name=str(metadata.get("display_name") or "内置基础增强"),
        version=str(metadata.get("version") or "builtin") or "builtin",
        description=str(metadata.get("description") or ""),
        dataset_types=[str(item) for item in metadata.get("dataset_types", []) if str(item).strip()],
        author=str(metadata.get("author") or "系统内置"),
    )
