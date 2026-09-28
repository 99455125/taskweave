"""Validation for plugin-owned authoring evidence and previews."""

from dataclasses import asdict
import json

from taskweave.core.ports import ContextCollection, ContextItem, ContextView
from taskweave.core.validation import TaskError


def serialize_context_collection(capture, renderers):
    if not isinstance(capture, ContextCollection):
        raise TaskError("CONTEXT_RESULT_INVALID", "上下文采集器必须返回 ContextCollection")
    items = []
    for item in capture.items:
        if not isinstance(item, ContextItem):
            raise TaskError("CONTEXT_RESULT_INVALID", "上下文内容类型无效")
        items.append(asdict(item))
    views, titles = [], set()
    for view in capture.views:
        if not isinstance(view, ContextView) or not view.title.strip():
            raise TaskError("CONTEXT_VIEW_INVALID", "上下文预览需要标题")
        if view.title in titles:
            raise TaskError("CONTEXT_VIEW_INVALID", "上下文预览标题不能重复")
        if view.renderer not in renderers:
            raise TaskError("CONTEXT_VIEW_INVALID", "上下文预览渲染器不可用")
        titles.add(view.title)
        try:
            json.dumps(view.data, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise TaskError("CONTEXT_VIEW_INVALID", "上下文预览数据必须可保存为 JSON") from exc
        views.append(asdict(view))
    return {"items": items, "views": views}


def capture_ai_payload(capture, index, renderers):
    """Project selected previews into evidence without changing stored captures."""
    preview_items = []
    if capture.get("send_preview"):
        for view in capture.get("views", []):
            kind = renderers.get(view.get("renderer"), {}).get("type")
            data = view.get("data")
            title = view.get("title") or "预览"
            if kind == "image" or (isinstance(data, dict) and data.get("image_base64")):
                if not isinstance(data, dict) or not data.get("image_base64"):
                    raise TaskError("CONTEXT_VIEW_INVALID", f"{title} 没有可发送的内嵌图片")
                import base64
                import binascii
                if data.get("mime_type", "image/png") not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                    raise TaskError("CONTEXT_VIEW_INVALID", f"{title} 的图片格式不支持发送给 AI")
                try:
                    base64.b64decode(data["image_base64"], validate=True)
                except (ValueError, TypeError, binascii.Error) as exc:
                    raise TaskError("CONTEXT_VIEW_INVALID", f"{title} 的图片数据无效") from exc
                preview_items.append({"kind": "image", "title": title,
                                      "mime_type": data.get("mime_type", "image/png"),
                                      "content": data["image_base64"]})
            else:
                preview_items.append({"kind": "text", "title": title,
                                      "mime_type": "application/json", "renderer": view.get("renderer"),
                                      "content": json.dumps(data, ensure_ascii=False)})
    return {
        "capture_id": capture.get("capture_id"), "label": capture.get("label") or f"采集 {index + 1}",
        "operation_notes": capture.get("operation_notes", ""),
        "capture_index": index, "captured_at": capture.get("captured_at"),
        "items": capture.get("items", []), "preview_items": preview_items,
    }
