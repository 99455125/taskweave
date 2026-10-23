"""Deterministic evidence provider for external AI integration tests."""

from taskweave.core.ports import ContextCollection, ContextItem, ContextView
from taskweave.core.capability_contracts import Diagnostic
from taskweave.plugins.registry import Registry
from tests.test_context_targets_runtime import TargetPlugin


class EvidencePlugin(TargetPlugin):
    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        text = "with-preview" if include_view else "text-only"
        views = (ContextView("截图", "core.image", {"image_base64": "aW1hZ2U=", "mime_type": "image/png"}),) if include_view else ()
        return ContextCollection((ContextItem("text", "text/plain", text, "demo.page"),), views)

    async def lint(self, document):
        if document["name"] == "lint-error":
            return [Diagnostic("REQUIRED_ACTION_ARGUMENT", "缺少动作必录参数", severity="error")]
        return []


def build_registry():
    return Registry([EvidencePlugin()])
