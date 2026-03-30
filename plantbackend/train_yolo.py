import argparse
import json
import shutil
import types
from datetime import datetime
from pathlib import Path
from typing import List, Optional

PROGRESS_PREFIX = "__TRAIN_PROGRESS__"


def load_classes(classes_file: Path) -> List[str]:
    if not classes_file.exists():
        raise RuntimeError(f"Classes file not found: {classes_file}")

    classes = [line.strip() for line in classes_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not classes:
        raise RuntimeError(f"No classes found in: {classes_file}")
    return classes


def find_best_weights(model) -> Path:
    trainer = getattr(model, "trainer", None)
    candidates: List[Path] = []

    if trainer is not None:
        best = getattr(trainer, "best", None)
        if best:
            candidates.append(Path(best))

        save_dir = getattr(trainer, "save_dir", None)
        if save_dir:
            save_dir = Path(save_dir)
            candidates.append(save_dir / "weights" / "best.pt")
            candidates.append(save_dir / "weights" / "last.pt")

    ckpt_path = getattr(model, "ckpt_path", None)
    if ckpt_path:
        candidates.append(Path(ckpt_path))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
            return candidate.resolve()

    raise RuntimeError("Unable to locate trained .pt weights after training.")


def emit_progress(
    *,
    stage: str,
    message: str,
    progress: float,
    current_epoch: Optional[int] = None,
    total_epochs: Optional[int] = None,
) -> None:
    payload = {
        "stage": stage,
        "message": message,
        "progress": max(0.0, min(float(progress), 1.0)),
        "current_epoch": current_epoch,
        "total_epochs": total_epochs,
    }
    print(f"{PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def patch_legacy_c2f_for_export(model) -> int:
    """Patch legacy C2f blocks so Ultralytics ONNX export can switch to forward_split safely."""
    try:
        import torch
        from ultralytics.nn.modules.block import C2f
    except Exception:
        return 0

    patched = 0
    for module in model.model.modules():
        if isinstance(module, C2f) and not hasattr(module, "mesf"):
            def legacy_forward_split(self, x):
                y = self.cv1(x).split((self.c, self.c), 1)
                y = [y[0], y[1]]
                y.extend(block(y[-1]) for block in self.m)
                return self.cv2(torch.cat(y, 1))

            module.forward_split = types.MethodType(legacy_forward_split, module)
            patched += 1

    return patched


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a YOLO model and export it to ONNX.")
    parser.add_argument("--dataset", required=True, help="Path to dataset.yaml")
    parser.add_argument("--classes-file", required=True, help="Path to dataset classes.txt")
    parser.add_argument("--dataset-name", required=True, help="Logical dataset name")
    parser.add_argument("--base-model", default="yolov8n.pt", help="Base YOLO .pt file or model name")
    parser.add_argument("--epochs", type=int, default=30, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Training/export image size")
    parser.add_argument("--workers", type=int, default=0, help="Dataloader workers")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience")
    parser.add_argument("--device", default="", help="Training device, e.g. cpu, 0, 0,1")
    parser.add_argument("--project", required=True, help="Training runs project directory")
    parser.add_argument("--name", required=True, help="Training run name")
    parser.add_argument("--output-model", required=True, help="Final ONNX path")
    parser.add_argument("--labels-output", required=True, help="Per-model class labels JSON output path")
    parser.add_argument("--metadata-output", required=True, help="Metadata JSON output path")
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    classes_file = Path(args.classes_file).resolve()
    project_dir = Path(args.project).resolve()
    output_model = Path(args.output_model).resolve()
    labels_output = Path(args.labels_output).resolve()
    metadata_output = Path(args.metadata_output).resolve()

    output_model.parent.mkdir(parents=True, exist_ok=True)
    labels_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    classes = load_classes(classes_file)
    emit_progress(stage="preparing", message="已加载数据集配置，正在初始化训练环境。", progress=0.02)

    try:
        from ultralytics import YOLO
    except Exception as exc:
        detail = str(exc)
        if "libxcb.so.1" in detail or "cv2" in detail:
            raise RuntimeError(
                "Ultralytics import failed because OpenCV system libraries are missing. "
                "On Arch/WSL, install them with: sudo pacman -Syu --needed libxcb mesa glib2 "
                "and then retry training."
            ) from exc
        raise RuntimeError(
            "Ultralytics is not available in the current Python environment. "
            "Please install ultralytics and torch first."
        ) from exc

    model = YOLO(args.base_model)

    def on_train_start(trainer) -> None:
        total_epochs = int(getattr(trainer, "epochs", max(1, int(args.epochs))))
        emit_progress(
            stage="training",
            message="训练已启动，正在进行首轮迭代。",
            progress=0.05,
            current_epoch=0,
            total_epochs=total_epochs,
        )

    def on_fit_epoch_end(trainer) -> None:
        total_epochs = max(1, int(getattr(trainer, "epochs", max(1, int(args.epochs)))))
        current_epoch = min(total_epochs, int(getattr(trainer, "epoch", 0)) + 1)
        progress = 0.05 + (current_epoch / total_epochs) * 0.9
        emit_progress(
            stage="training",
            message=f"训练进行中：第 {current_epoch}/{total_epochs} 轮已完成。",
            progress=progress,
            current_epoch=current_epoch,
            total_epochs=total_epochs,
        )

    def on_train_end(trainer) -> None:
        total_epochs = max(1, int(getattr(trainer, "epochs", max(1, int(args.epochs)))))
        current_epoch = min(total_epochs, int(getattr(trainer, "epoch", total_epochs - 1)) + 1)
        emit_progress(
            stage="exporting",
            message="训练结束，正在导出 ONNX 模型。",
            progress=0.97,
            current_epoch=current_epoch,
            total_epochs=total_epochs,
        )

    model.add_callback("on_train_start", on_train_start)
    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
    model.add_callback("on_train_end", on_train_end)
    train_kwargs = {
        "data": str(dataset_path),
        "epochs": max(1, int(args.epochs)),
        "imgsz": max(32, int(args.imgsz)),
        "project": str(project_dir),
        "name": args.name,
        "exist_ok": True,
        "workers": max(0, int(args.workers)),
        "patience": max(1, int(args.patience)),
    }
    if args.device.strip():
        train_kwargs["device"] = args.device.strip()

    model.train(**train_kwargs)
    best_weights = find_best_weights(model)

    emit_progress(stage="exporting", message="正在加载最佳权重并导出 ONNX。", progress=0.98)
    export_model = YOLO(str(best_weights))
    patched_c2f = patch_legacy_c2f_for_export(export_model)
    if patched_c2f:
        emit_progress(
            stage="exporting",
            message=f"正在应用导出兼容补丁并导出 ONNX（已修复 {patched_c2f} 个旧版 C2f 层）。",
            progress=0.985,
        )
    try:
        import onnx  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "ONNX export dependency is missing. Please install it in the training environment with: "
            "python -m pip install onnx"
        ) from exc

    try:
        exported_path = Path(export_model.export(format="onnx", imgsz=max(32, int(args.imgsz)))).resolve()
    except Exception as exc:
        detail = str(exc)
        if "No module named 'onnx'" in detail or 'No module named "onnx"' in detail:
            raise RuntimeError(
                "ONNX export dependency is missing. Please install it in the training environment with: "
                "python -m pip install onnx"
            ) from exc
        raise RuntimeError(f"ONNX export failed: {detail}") from exc
    shutil.copy2(exported_path, output_model)

    labels_output.write_text(
        json.dumps(classes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    metadata = {
        "dataset_name": args.dataset_name,
        "base_model": args.base_model,
        "epochs": max(1, int(args.epochs)),
        "imgsz": max(32, int(args.imgsz)),
        "classes": classes,
        "class_count": len(classes),
        "weights_path": str(best_weights),
        "exported_tmp_path": str(exported_path),
        "onnx_path": str(output_model),
        "labels_path": str(labels_output),
        "run_dir": str(best_weights.parent.parent),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    emit_progress(stage="completed", message="训练和导出已完成。", progress=1.0)
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
