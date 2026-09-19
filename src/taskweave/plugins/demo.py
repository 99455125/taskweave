"""Small local test adapters, not browser implementations."""

import asyncio
from taskweave.core.ports import CapabilitySpec, AuthoringContribution, PreparedResult
from taskweave.plugins.registry import Registry


class Echo:
    spec = CapabilitySpec(
        "demo.echo",
        "Return input values unchanged",
        {"type": "object"},
        {"type": "object"},
        "READ",
    )

    async def preflight(self, ctx, inputs):
        return []

    async def execute(self, ctx, inputs):
        return inputs

    async def verify(self, ctx, inputs, output):
        return []


class Wait(Echo):
    spec = CapabilitySpec(
        "demo.wait",
        "Wait locally, checking cancellation",
        {
            "type": "object",
            "properties": {"seconds": {"type": "number", "minimum": 0, "maximum": 120}},
            "required": ["seconds"],
            "additionalProperties": False,
        },
        {"type": "null"},
        "READ",
        timeout_ms=125000,
    )

    async def execute(self, ctx, inputs):
        remaining = inputs["seconds"]
        while remaining > 0:
            if ctx.cancelled():
                return None
            delay = min(remaining, 0.05)
            await asyncio.sleep(delay)
            remaining -= delay
        return None


class TableResult:
    def schema(self):
        return {"tables": {"p_demo_items": {"value": "TEXT"}}}

    def prepare(self, request):
        return PreparedResult("table", table_name="p_demo_items", rows=request.payload)

    def parse(self, stored):
        return [row["value"] for row in stored]

    def preview(self, parsed):
        return {"values": parsed}


class DemoPlugin:
    def manifest(self):
        return {"id": "demo", "api_version": 1, "package_version": "1.0.0"}

    def actions(self):
        return {"demo.echo": Echo(), "demo.wait": Wait()}

    def tools(self):
        return {"demo.echo": Echo()}

    def result_handlers(self):
        return {"demo.table": TableResult()}

    def resource_providers(self):
        return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            "demo.echo returns the input object unchanged; demo.wait takes seconds.",
            ('return ctx.result(data=await ctx.call("demo.echo", inputs))',),
            tool_ids=("demo.echo",),
        )

    async def lint(self, document):
        return []

    async def collect_context(self, provider_id, ctx, request):
        return []

    async def diagnose(self, error, refs):
        return []


class TextPlugin(DemoPlugin):
    def manifest(self):
        return {"id": "text", "api_version": 1, "package_version": "1.0.0"}

    def actions(self):
        return {"text.upper": Upper()}

    def tools(self):
        return {}

    def result_handlers(self):
        return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            "text.upper requires a text string and returns uppercase text."
        )


class Upper(Echo):
    spec = CapabilitySpec(
        "text.upper",
        "Uppercase a string",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        {"type": "string"},
        "READ",
    )

    async def execute(self, ctx, inputs):
        return inputs["text"].upper()


def build_registry():
    return Registry([DemoPlugin(), TextPlugin()])
