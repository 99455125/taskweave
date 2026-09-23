"""Portable task package v2 structural contract."""

FORMAT = "taskweave-task-2"
ORIGINS = {"ai_generated", "task_export"}
VALIDATION_STATES = {"DRAFT", "VALIDATED"}

JSON_SCHEMA = {"type": "object"}
STEP_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "step_description": {"type": "string"}, "step_notes": {"type": "string"},
        "step_content": {"type": "string"}, "input_schema": JSON_SCHEMA,
        "output_schema": JSON_SCHEMA, "bindings": {"type": "object"},
        "capabilities": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "plugin_requirements": {"type": "object", "additionalProperties": {"type": "string"}},
        "timeout_ms": {"type": "integer", "minimum": 1},
        "delay_after_previous_seconds": {"type": "integer", "minimum": 0},
        "content_format": {"const": "python-async-v1"},
    },
    "required": ["name", "step_description", "step_notes", "step_content", "input_schema", "output_schema", "bindings", "capabilities", "plugin_requirements", "timeout_ms", "delay_after_previous_seconds", "content_format"],
    "additionalProperties": False,
}

TASK_PACKAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "format": {"const": FORMAT},
        "origin": {"enum": sorted(ORIGINS)},
        "task": {"type": "object", "properties": {
            "name": {"type": "string", "minLength": 1}, "description": {"type": "string"}, "input_schema": JSON_SCHEMA,
        }, "required": ["name", "description", "input_schema"], "additionalProperties": False},
        "steps": {"type": "array", "maxItems": 1000, "items": {
            "type": "object", "properties": {
                "key": {"type": "string", "minLength": 1},
                "validation_state": {"enum": sorted(VALIDATION_STATES)},
                "document": STEP_DOCUMENT_SCHEMA,
            }, "required": ["key", "validation_state", "document"], "additionalProperties": False,
        }},
    },
    "required": ["format", "origin", "task", "steps"],
    "additionalProperties": False,
}
