"""Browser action input schemas shared by assembly and tools."""



def schema(properties=None, required=()):
    return {
        "type": "object",
        "properties": {
            "role": {"type": "string", "minLength": 1},
            "target_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 20000},
            **(properties or {}),
        },
        "required": list(required),
        "$defs": {"locator": LOCATOR},
        "additionalProperties": False,
    }


STRING = {"type": "string"}
NULL = {"type": "null"}
LOCATOR = {"oneOf": [
    {"type": "string", "minLength": 1},
    {"type": "object", "properties": {
        "kind": {"enum": ["css", "role", "label", "placeholder"]},
        "value": {"type": "string", "minLength": 1},
        "name": {"type": "string"}, "frame": {"oneOf": [
            {"type": "string", "minLength": 1},
            {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "minLength": 1}}]},
        "within": {"$ref": "#/$defs/locator"},
        "nth": {"type": "integer", "minimum": 0, "maximum": 9999},
        "exact": {"type": "boolean"}}, "required": ["kind", "value"], "additionalProperties": False}
]}


INSPECT_PARAMETERS = {
    'scope': {'enum': ['runtime', 'viewport', 'full_page']}, 'selector': LOCATOR,
    'include_ancestors': {'type': 'boolean'}, 'include_descendants': {'type': 'boolean'},
    'depth': {'type': 'integer', 'minimum': 0, 'maximum': 6},
    'max_nodes': {'type': 'integer', 'minimum': 1, 'maximum': 300},
    'interactive_only': {'type': 'boolean'},
}
