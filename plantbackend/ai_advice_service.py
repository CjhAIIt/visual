"""AI recommendation service with multimodal and text-only fallbacks.

If an OpenAI-compatible endpoint is configured and the model supports image
input, the service sends the uploaded plant image together with recognition
context for image-grounded analysis. If image input is unsupported, it falls
back to text-only advice based on the local prediction output. When no remote
service is available, deterministic builtin advice keeps the API stable.
"""

import base64
import io
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request
from urllib.parse import urljoin

from PIL import Image

try:
    from .config import settings
except ImportError:
    from config import settings


def _strip_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_first_json_object(text: str) -> str:
    candidate = str(text or "").strip()
    if not candidate:
        return ""

    start = candidate.find("{")
    if start < 0:
        return candidate

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(candidate[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return candidate[start:index + 1]

    return candidate


def _extract_message_text(payload: Dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)

    return ""


def _build_endpoint_url(api_url: str, base_url: str, chat_path: str) -> str:
    explicit_url = str(api_url or "").strip()
    if explicit_url:
        return explicit_url

    normalized_base = str(base_url or "").strip()
    normalized_path = str(chat_path or "").strip()
    if not normalized_base or not normalized_path:
        return ""

    return urljoin(f"{normalized_base.rstrip('/')}/", normalized_path.lstrip("/"))


def _normalize_image_content_type(image_content_type: Optional[str]) -> str:
    normalized = str(image_content_type or "").strip().lower()
    if normalized.startswith("image/"):
        return normalized
    return "image/jpeg"


def _prepare_image_for_api(
    image_bytes: bytes,
    image_content_type: Optional[str],
    max_bytes: int,
) -> Tuple[Optional[bytes], Optional[str]]:
    if not image_bytes:
        return None, None

    safe_type = _normalize_image_content_type(image_content_type)
    if len(image_bytes) <= max_bytes:
        return image_bytes, safe_type

    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")

        if max(image.size) > 1568:
            image.thumbnail((1568, 1568))

        for quality in (88, 80, 72, 64, 56):
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            candidate = buffer.getvalue()
            if len(candidate) <= max_bytes:
                return candidate, "image/jpeg"
    except Exception:
        return None, None

    return None, None


def _summarize_remote_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "远端大模型接口超时。"
    if isinstance(exc, error.URLError):
        return f"无法连接远端大模型接口：{exc.reason}"
    if isinstance(exc, error.HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        detail = ""
        if body:
            try:
                payload = json.loads(body)
                detail = str(payload.get("error", {}).get("message") or payload.get("detail") or "").strip()
            except Exception:
                detail = body.strip()
        return f"远端大模型接口返回 HTTP {exc.code}{f'：{detail}' if detail else ''}"
    if isinstance(exc, ValueError):
        return str(exc) or "远端大模型响应无效。"
    return str(exc) or "远端大模型请求失败。"


def build_fallback_advice(
    disease_label: str,
    confidence: float = 0.0,
    detail: str = "",
) -> Dict[str, object]:
    safe_label = str(disease_label or "未知病害").strip() or "未知病害"
    translated_confidence = f"{confidence * 100:.1f}%"
    payload = {
        "disease_label": safe_label,
        "summary": f"系统根据当前识别结果判断为 {safe_label}，当前置信度约为 {translated_confidence}。建议先复查叶片症状，再尽快采取隔离、通风和病叶清理措施。",
        "advice": [
            "先检查同一植株及周边叶片，确认是否出现类似病斑并及时隔离重病叶片。",
            "保持种植环境通风、降湿，避免叶面长期积水，减少病害继续扩散。",
            "结合当地农技建议或植保方案，尽快选择对应病害的防治措施并持续观察 3 到 5 天。",
        ],
        "source": "builtin",
    }
    if detail:
        payload["detail"] = detail
    return payload


class AiAdviceService:
    def __init__(self) -> None:
        self.api_url = str(settings.ai_api_url or "").strip()
        self.api_base_url = str(settings.ai_api_base_url or "").strip()
        self.api_chat_path = str(settings.ai_api_chat_path or "").strip()
        self.endpoint_url = _build_endpoint_url(self.api_url, self.api_base_url, self.api_chat_path)
        self.api_key = str(settings.ai_api_key or "").strip()
        self.model_name = str(settings.ai_api_model or "").strip()
        self.timeout = max(5, int(settings.ai_api_timeout))
        self.max_image_bytes = max(256 * 1024, int(settings.ai_api_max_image_bytes))
        self.image_detail = str(settings.ai_api_image_detail or "auto").strip() or "auto"

    def _is_configured(self) -> bool:
        return bool(self.endpoint_url and self.model_name)

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _perform_request(self, payload: Dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.endpoint_url,
            data=body,
            method="POST",
            headers=self._build_headers(),
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def _post_chat_payload(self, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        try:
            raw_text = self._perform_request(payload)
        except error.HTTPError as exc:
            if "response_format" not in payload:
                return None, _summarize_remote_error(exc)
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            try:
                raw_text = self._perform_request(retry_payload)
            except (error.URLError, error.HTTPError, TimeoutError, ValueError) as retry_exc:
                return None, _summarize_remote_error(retry_exc)
        except (error.URLError, TimeoutError, ValueError) as exc:
            return None, _summarize_remote_error(exc)

        try:
            return json.loads(raw_text), ""
        except (TypeError, ValueError, json.JSONDecodeError):
            return None, "远端大模型返回了无法解析的 JSON 响应。"

    def _parse_result(self, payload: Dict[str, Any], disease_label: str, confidence: float, source: str) -> Optional[Dict[str, object]]:
        raw_content = _extract_message_text(payload)
        cleaned_text = _extract_first_json_object(_strip_code_fences(raw_content))
        if not cleaned_text:
            return None

        try:
            parsed = json.loads(cleaned_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

        summary = str(parsed.get("summary") or "").strip()
        advice_raw = parsed.get("advice")
        if isinstance(advice_raw, list):
            advice_items = advice_raw
        elif advice_raw:
            advice_items = [advice_raw]
        else:
            advice_items = []

        cleaned_advice = [str(item).strip() for item in advice_items if str(item).strip()]
        if not summary:
            return None
        if not cleaned_advice:
            cleaned_advice = list(build_fallback_advice(disease_label, confidence)["advice"])

        return {
            "disease_label": disease_label,
            "summary": summary,
            "advice": cleaned_advice[:5],
            "source": source,
        }

    def _build_text_payload(self, disease_label: str, confidence: float, top_predictions: List[Dict[str, object]]) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是农业植保助手。请根据植物病害识别结果，给出谨慎、简洁、可执行的中文建议。"
                        "不要编造没有提供的图像细节。必须只返回 JSON，不要加 Markdown。"
                        '格式固定为：{"summary":"一句话总结","advice":["建议1","建议2","建议3"]}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "disease_label": disease_label,
                            "confidence": confidence,
                            "top_predictions": top_predictions[:3],
                            "task": "请基于识别结果给出适合前端直接展示的诊断总结与处理建议。",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

    def _build_class_knowledge_payload(self, class_name: str) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是农业植保知识库助手。请根据给定的植物病害或作物类别名称，"
                        "返回适合长期存入系统知识库的中文建议。"
                        "如果类别是健康叶片、正常状态或信息不足，请给出保守的养护与观察建议。"
                        "不要输出 Markdown，不要虚构没有依据的具体药剂和剂量。"
                        '必须只返回 JSON，格式固定为：{"summary":"一句话总结","advice":["建议1","建议2","建议3"]}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "class_name": class_name,
                            "task": "请基于类别名称生成适合前端直接展示和长期缓存的总结与处理建议。",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

    def _build_vision_payload(
        self,
        image_bytes: bytes,
        image_content_type: Optional[str],
        disease_label: str,
        confidence: float,
        top_predictions: List[Dict[str, object]],
    ) -> Optional[Dict[str, Any]]:
        prepared_image_bytes, prepared_content_type = _prepare_image_for_api(
            image_bytes=image_bytes,
            image_content_type=image_content_type,
            max_bytes=self.max_image_bytes,
        )
        if not prepared_image_bytes or not prepared_content_type:
            return None

        data_url = "data:{};base64,{}".format(
            prepared_content_type,
            base64.b64encode(prepared_image_bytes).decode("ascii"),
        )
        return {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是农业植保助手。请先观察图片本身，再参考机器识别结果，输出谨慎、简洁、可执行的中文分析。"
                        "如果图片信息不足或无法确认病害，请明确说明，不要过度确定。"
                        "必须只返回 JSON，不要加 Markdown。"
                        '格式固定为：{"summary":"一句话总结，需体现可见症状与总体判断","advice":["建议1","建议2","建议3"]}'
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "recognition_result": {
                                        "disease_label": disease_label,
                                        "confidence": confidence,
                                        "top_predictions": top_predictions[:3],
                                    },
                                    "task": "请结合图片可见症状和识别结果，先概括叶片当前情况，再给出 3 条处理建议。",
                                },
                                ensure_ascii=False,
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                                "detail": self.image_detail,
                            },
                        },
                    ],
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

    def _call_remote_text_ai(
        self,
        disease_label: str,
        confidence: float,
        top_predictions: List[Dict[str, object]],
    ) -> Tuple[Optional[Dict[str, object]], str]:
        if not self._is_configured():
            return None, ""

        payload = self._build_text_payload(disease_label, confidence, top_predictions)
        raw_payload, error_detail = self._post_chat_payload(payload)
        if not raw_payload:
            return None, error_detail
        return self._parse_result(raw_payload, disease_label, confidence, "ai-text"), ""

    def _call_remote_vision_ai(
        self,
        image_bytes: bytes,
        image_content_type: Optional[str],
        disease_label: str,
        confidence: float,
        top_predictions: List[Dict[str, object]],
    ) -> Tuple[Optional[Dict[str, object]], str]:
        if not self._is_configured() or not image_bytes:
            return None, ""

        payload = self._build_vision_payload(
            image_bytes=image_bytes,
            image_content_type=image_content_type,
            disease_label=disease_label,
            confidence=confidence,
            top_predictions=top_predictions,
        )
        if not payload:
            return None, "图片无法压缩到远端多模态接口允许的大小范围内。"

        raw_payload, error_detail = self._post_chat_payload(payload)
        if not raw_payload:
            return None, error_detail
        return self._parse_result(raw_payload, disease_label, confidence, "ai-vision"), ""

    def generate(
        self,
        disease_label: str,
        confidence: float = 0.0,
        top_predictions: Optional[List[Dict[str, object]]] = None,
        image_bytes: Optional[bytes] = None,
        image_content_type: Optional[str] = None,
    ) -> Dict[str, object]:
        safe_label = str(disease_label or "No detection").strip() or "No detection"
        safe_predictions = list(top_predictions or [])
        remote_failure_detail = ""

        if image_bytes:
            vision_result, vision_error_detail = self._call_remote_vision_ai(
                image_bytes=image_bytes,
                image_content_type=image_content_type,
                disease_label=safe_label,
                confidence=confidence,
                top_predictions=safe_predictions,
            )
            if vision_result:
                return vision_result
            if vision_error_detail:
                remote_failure_detail = vision_error_detail

        if safe_label != "No detection":
            remote_text_result, text_error_detail = self._call_remote_text_ai(
                disease_label=safe_label,
                confidence=confidence,
                top_predictions=safe_predictions,
            )
            if remote_text_result:
                return remote_text_result
            if text_error_detail:
                remote_failure_detail = text_error_detail

            return build_fallback_advice(safe_label, confidence, remote_failure_detail)

        return {
            "disease_label": "No detection",
            "summary": "当前没有识别到明确病害目标，建议重新拍摄更清晰的叶片图像后再识别。",
            "advice": [
                "尽量在光线充足的环境下重新拍摄。",
                "让叶片主体尽量完整并靠近画面中心。",
                "如果仍无法识别，可结合人工观察进一步判断。",
            ],
            "source": "builtin",
        }

    def generate_class_knowledge(self, class_name: str) -> Dict[str, object]:
        safe_label = str(class_name or "未知类别").strip() or "未知类别"
        if not self._is_configured():
            return build_fallback_advice(safe_label, 1.0)

        payload = self._build_class_knowledge_payload(safe_label)
        raw_payload, error_detail = self._post_chat_payload(payload)
        if raw_payload:
            parsed = self._parse_result(raw_payload, safe_label, 1.0, "ai-text")
            if parsed:
                return parsed
            error_detail = error_detail or "远端大模型返回了无法解析的建议内容。"

        return build_fallback_advice(safe_label, 1.0, error_detail)
