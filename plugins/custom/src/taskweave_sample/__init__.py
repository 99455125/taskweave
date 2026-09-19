"""Independent example using only the public TaskWeave SDK."""

from taskweave.plugins.sdk import CapabilitySpec, AuthoringContribution, PreparedResult


class Upper:
    spec = CapabilitySpec(
        "sample.upper",
        "Uppercase text",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        {"type": "string"},
        "READ",
    )

    async def preflight(self, ctx, inputs):
        return []

    async def execute(self, ctx, inputs):
        return inputs["text"].upper()

    async def verify(self, ctx, inputs, output):
        return []


class Rows:
    def schema(self):
        return {"version": 1, "tables": {"p_sample_rows": {"value": "TEXT"}}}

    def prepare(self, request):
        return PreparedResult("table", table_name="p_sample_rows", rows=request.payload)

    def parse(self, stored):
        return [r["value"] for r in stored]

    def preview(self, parsed):
        return {"items": parsed}


class SamplePlugin:
    def manifest(self):
        return {
            "id": "sample",
            "api_version": 1,
            "package_version": "0.1.0",
            "core_requires": ">=0.1,<1",
            "dependencies": {},
        }

    def actions(self):
        return {"sample.upper": Upper()}

    def tools(self):
        return {"sample.upper": Upper()}

    def result_handlers(self):
        return {"sample.rows": Rows()}

    def resource_providers(self):
        return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            "sample.upper accepts {text: string} and returns uppercase text.",
            tool_ids=("sample.upper",),
            constraints={"content_format": "python-async-v1"},
        )

    async def lint(self, step_document):
        return []

    async def collect_context(self, provider_id, ctx, request):
        return []

    async def diagnose(self, error, refs):
        return []
