"""ONNX model loading and prediction utilities."""

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import onnxruntime as ort
from PIL import Image

try:
    from .config import settings
except ImportError:
    from config import settings


class ModelService:
    def __init__(self) -> None:
        # Cache inference sessions by filename so model switching does not keep
        # reopening the same ONNX asset during a demo.
        self.sessions: Dict[str, ort.InferenceSession] = {}
        self.model_errors: Dict[str, str] = {}
        self.class_name_cache: Dict[str, List[str]] = {}
        self.input_size_cache: Dict[str, Tuple[int, int]] = {}
        self.default_class_names = self._safe_load_class_names(Path(settings.class_names_path))
        self.input_size = (settings.input_width, settings.input_height)
        self.current_model_name: Optional[str] = None
        self.load_error: Optional[str] = None
        self._initialize_default_model()

    @property
    def is_ready(self) -> bool:
        return self.current_model_name is not None and self.current_model_name in self.sessions

    def available_models(self) -> List[str]:
        models_dir = Path(settings.models_dir)
        if not models_dir.exists():
            return []
        return sorted(
            [path.name for path in models_dir.glob("*.onnx") if path.is_file() and path.stat().st_size > 0]
        )

    def set_active_model(self, model_name: str) -> str:
        self.ensure_model_ready(model_name)
        self.current_model_name = model_name
        return model_name

    def ensure_model_ready(self, model_name: str) -> str:
        session = self._ensure_model_session(model_name)
        if session is None:
            raise RuntimeError(self.model_errors.get(model_name, f"模型尚未就绪：{model_name}"))
        self.load_error = None
        return model_name

    def _initialize_default_model(self) -> None:
        available = self.available_models()
        if not available:
            self.load_error = f"当前没有可用的 ONNX 模型：{settings.models_dir}"
            return

        default_name = settings.default_model_name if settings.default_model_name in available else available[0]
        try:
            self.set_active_model(default_name)
        except RuntimeError as exc:
            self.load_error = str(exc)

    def _load_class_names(self, class_names_path: Path) -> List[str]:
        # 读取类别名称，让模型输出的索引能映射成病害名称。
        if not class_names_path.exists():
            raise RuntimeError(f"类别名称文件不存在：{class_names_path}")

        with class_names_path.open("r", encoding="utf-8") as file:
            class_names = json.load(file)

        if not isinstance(class_names, list) or not all(
            isinstance(name, str) for name in class_names
        ):
            raise RuntimeError("类别名称文件必须是由字符串组成的 JSON 数组。")

        return class_names

    def _safe_load_class_names(self, class_names_path: Path) -> List[str]:
        try:
            return self._load_class_names(class_names_path)
        except Exception:
            return []

    def _resolve_model_path(self, model_name: str) -> Path:
        return Path(settings.models_dir) / model_name

    def _resolve_model_class_names(self, model_name: str) -> List[str]:
        if model_name in self.class_name_cache:
            return self.class_name_cache[model_name]

        model_path = self._resolve_model_path(model_name)
        labels_path = model_path.with_suffix(".labels.json")
        if labels_path.exists():
            try:
                class_names = self._load_class_names(labels_path)
                self.class_name_cache[model_name] = class_names
                return class_names
            except Exception as exc:
                self.model_errors[model_name] = f"加载模型标签元数据失败：{model_name}：{exc}"
                raise RuntimeError(self.model_errors[model_name]) from exc

        self.class_name_cache[model_name] = list(self.default_class_names)
        return self.class_name_cache[model_name]

    def _resolve_model_input_size(self, model_name: str, session: ort.InferenceSession) -> Tuple[int, int]:
        if model_name in self.input_size_cache:
            return self.input_size_cache[model_name]

        input_size = self.input_size
        try:
            input_meta = session.get_inputs()[0]
            shape = list(input_meta.shape)
            width = shape[3] if len(shape) >= 4 else None
            height = shape[2] if len(shape) >= 4 else None
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                input_size = (width, height)
            else:
                metadata_path = self._resolve_model_path(model_name).with_suffix(".meta.json")
                if metadata_path.exists():
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    imgsz = int(metadata.get("imgsz") or 0)
                    if imgsz > 0:
                        input_size = (imgsz, imgsz)
        except Exception:
            input_size = self.input_size

        self.input_size_cache[model_name] = input_size
        return input_size

    def _ensure_model_session(self, model_name: str) -> Optional[ort.InferenceSession]:
        if model_name in self.sessions:
            return self.sessions[model_name]

        model_path = self._resolve_model_path(model_name)
        if not model_path.exists() or model_path.stat().st_size == 0:
            self.model_errors[model_name] = f"ONNX 模型尚未就绪：{model_path}"
            return None

        try:
            session_options = ort.SessionOptions()
            session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session = ort.InferenceSession(
                str(model_path),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            )
            self.sessions[model_name] = session
            self.model_errors.pop(model_name, None)
            return session
        except Exception as exc:
            self.model_errors[model_name] = f"加载 ONNX 模型失败：{model_name}：{exc}"
            return None

    def _preprocess(self, image_bytes: bytes, input_size: Tuple[int, int]) -> Tuple[np.ndarray, Tuple[int, int]]:
        # Read, normalize, and reshape the image into the tensor layout expected
        # by the YOLO-style ONNX models we serve.
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise ValueError("无效的图片文件。") from exc

        original_size = image.size
        image = image.resize(input_size)
        image_array = np.asarray(image, dtype=np.float32) / 255.0
        image_array = np.transpose(image_array, (2, 0, 1))
        image_array = np.expand_dims(image_array, axis=0)
        return image_array, original_size

    def predict(
        self,
        image_bytes: bytes,
        model_name: Optional[str] = None,
        confidence_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        # Main inference flow: preprocess -> model session -> YOLO postprocess.
        active_model_name = model_name or self.current_model_name
        if not active_model_name:
            detail = self.load_error or "模型会话尚未初始化。"
            raise RuntimeError(detail)

        session = self._ensure_model_session(active_model_name)
        if session is None:
            detail = self.model_errors.get(active_model_name, "模型会话尚未初始化。")
            raise RuntimeError(detail)

        self.current_model_name = active_model_name
        self.load_error = None

        class_names = self._resolve_model_class_names(active_model_name)
        input_size = self._resolve_model_input_size(active_model_name, session)
        input_tensor, original_size = self._preprocess(image_bytes, input_size)
        input_name = session.get_inputs()[0].name
        raw_output = session.run(None, {input_name: input_tensor})[0]

        detections = self._postprocess(
            np.squeeze(raw_output, axis=0),
            original_size,
            class_names,
            input_size,
            confidence_threshold=confidence_threshold,
        )
        if not detections:
            return {
                "model_name": active_model_name,
                "predicted_class": "No detection",
                "predicted_index": -1,
                "confidence": 0.0,
                "top_predictions": [],
                "detections": [],
            }

        top_detections = detections[: settings.top_k]
        primary = top_detections[0]

        return {
            "model_name": active_model_name,
            "predicted_class": primary["label"],
            "predicted_index": primary["class_index"],
            "confidence": primary["confidence"],
            "top_predictions": [
                {
                    "label": item["label"],
                    "confidence": item["confidence"],
                    "bbox": item["bbox"],
                }
                for item in top_detections
            ],
            "detections": [
                {
                    "label": item["label"],
                    "confidence": item["confidence"],
                    "bbox": item["bbox"],
                }
                for item in detections
            ],
        }

    def _postprocess(
        self,
        output: np.ndarray,
        original_size: Tuple[int, int],
        class_names: List[str],
        input_size: Tuple[int, int],
        confidence_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        # YOLO 检测输出格式是 [channels, anchors]，这里先转成 [anchors, channels]。
        predictions = output.T
        boxes = predictions[:, :4]
        class_scores = predictions[:, 4:]

        class_names = self._normalize_class_names(class_names, class_scores.shape[1])

        best_class_indices = np.argmax(class_scores, axis=1)
        best_scores = class_scores[np.arange(class_scores.shape[0]), best_class_indices]
        effective_confidence_threshold = settings.confidence_threshold if confidence_threshold is None else max(
            0.0,
            min(1.0, float(confidence_threshold)),
        )
        keep = best_scores >= effective_confidence_threshold

        boxes = boxes[keep]
        best_scores = best_scores[keep]
        best_class_indices = best_class_indices[keep]

        if len(boxes) == 0:
            return []

        scaled_boxes = self._scale_boxes_xywh_to_xyxy(boxes, original_size, input_size)
        keep_indices = self._nms(scaled_boxes, best_scores, settings.iou_threshold)

        detections: List[Dict[str, Any]] = []
        for index in keep_indices:
            class_index = int(best_class_indices[index])
            detections.append(
                {
                    "class_index": class_index,
                    "label": self._resolve_label(class_index, class_names),
                    "confidence": float(best_scores[index]),
                    "bbox": [float(value) for value in scaled_boxes[index]],
                }
            )

        detections.sort(key=lambda item: item["confidence"], reverse=True)
        return detections

    def _normalize_class_names(self, class_names: List[str], class_count: int) -> List[str]:
        if class_count <= 0:
            return []

        normalized = [str(name).strip() for name in class_names if str(name).strip()]
        if len(normalized) == class_count:
            return normalized

        if len(normalized) > class_count:
            return normalized[:class_count]

        generated = list(normalized)
        for index in range(len(generated), class_count):
            generated.append(f"class_{index}")
        return generated

    def _scale_boxes_xywh_to_xyxy(
        self,
        boxes: np.ndarray,
        original_size: Tuple[int, int],
        input_size: Tuple[int, int],
    ) -> np.ndarray:
        # 将模型输出的中心点宽高格式，转成前端更常用的左上右下格式。
        orig_w, orig_h = original_size
        input_w, input_h = input_size

        x_center = boxes[:, 0]
        y_center = boxes[:, 1]
        width = boxes[:, 2]
        height = boxes[:, 3]

        x1 = (x_center - width / 2) * (orig_w / input_w)
        y1 = (y_center - height / 2) * (orig_h / input_h)
        x2 = (x_center + width / 2) * (orig_w / input_w)
        y2 = (y_center + height / 2) * (orig_h / input_h)

        scaled = np.stack([x1, y1, x2, y2], axis=1)
        scaled[:, [0, 2]] = np.clip(scaled[:, [0, 2]], 0, orig_w)
        scaled[:, [1, 3]] = np.clip(scaled[:, [1, 3]], 0, orig_h)
        return scaled

    def _nms(
        self,
        boxes: np.ndarray,
        scores: np.ndarray,
        iou_threshold: float,
    ) -> List[int]:
        # 非极大值抑制：去掉高度重叠的重复检测框。
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
        order = scores.argsort()[::-1]
        keep: List[int] = []

        while order.size > 0:
            i = int(order[0])
            keep.append(i)
            if order.size == 1:
                break

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            inter_w = np.maximum(0, xx2 - xx1)
            inter_h = np.maximum(0, yy2 - yy1)
            intersection = inter_w * inter_h

            union = areas[i] + areas[order[1:]] - intersection
            iou = np.divide(
                intersection,
                union,
                out=np.zeros_like(intersection),
                where=union > 0,
            )

            remaining = np.where(iou <= iou_threshold)[0]
            order = order[remaining + 1]

        return keep

    def _resolve_label(self, index: int, class_names: List[str]) -> str:
        # 把输出索引转成可读类别名，避免前端只拿到数字。
        if 0 <= index < len(class_names):
            return class_names[index]
        return f"class_{index}"
