"""Content and binding rules; no database, model or browser dependency."""

import ast
import hashlib
import json
import re
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry


class TaskError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)

    def document(self):
        return {"code": self.code, "message": str(self)}


def dumps(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise TaskError("NOT_JSON", "Result must contain JSON values") from exc


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def valid_id(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise TaskError("INVALID_ID") from exc
    return value


def check_schema(schema):
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise TaskError("SCHEMA_INVALID", "Invalid JSON Schema") from exc

    def scan(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("$ref", "$dynamicRef") and not v.startswith("#"):
                    raise TaskError(
                        "SCHEMA_EXTERNAL_REF",
                        "Only local schema references are supported",
                    )
                if (
                    k == "$schema"
                    and v.rstrip("#") != "https://json-schema.org/draft/2020-12/schema"
                ):
                    raise TaskError("SCHEMA_DIALECT", "Use JSON Schema 2020-12")
                scan(v)
        elif isinstance(node, list):
            for v in node:
                scan(v)

    scan(schema)


def validate(value, schema):
    dumps(value)
    check_schema(schema)
    try:
        error = next(
            Draft202012Validator(schema, registry=Registry()).iter_errors(value), None
        )
    except Exception as exc:
        raise TaskError(
            "SCHEMA_INVALID", "Schema reference cannot be resolved"
        ) from exc
    if error:
        path = "/".join(str(x) for x in error.absolute_path)
        raise TaskError(
            "SCHEMA_MISMATCH", f"Invalid value at /{path}: {error.validator}"
        )


SAFE_BUILTINS = {
    name: value
    for name, value in vars(__import__("builtins")).items()
    if name
    in {
        "len",
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "tuple",
        "set",
        "range",
        "enumerate",
        "zip",
        "min",
        "max",
        "sum",
        "sorted",
        "abs",
        "round",
        "all",
        "any",
        "isinstance",
        "ValueError",
        "RuntimeError",
    }
}


def content_tree(source, capabilities):
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError) as exc:
        raise TaskError("CONTENT_INVALID", "Step must be valid Python") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.AsyncFunctionDef):
        raise TaskError("CONTENT_INVALID", "Use one async def run(ctx, inputs)")
    fn = tree.body[0]
    if (
        fn.name != "run"
        or [a.arg for a in fn.args.args] != ["ctx", "inputs"]
        or fn.args.defaults
        or fn.args.kwonlyargs
        or fn.args.posonlyargs
        or fn.args.vararg
        or fn.args.kwarg
        or fn.decorator_list
        or fn.returns
        or any(a.annotation for a in fn.args.args)
    ):
        raise TaskError(
            "CONTENT_INVALID",
            "Use exactly async def run(ctx, inputs) without annotations",
        )
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == 'ctx' and node.value.func.attr == 'output':
            raise TaskError('CONTENT_OUTPUT_UNUSED', 'ctx.output 只创建输出请求，必须把返回值放入 ctx.result(outputs=[...]) 才会保存')
        if isinstance(
            node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)
        ):
            raise TaskError(
                "CONTENT_FORBIDDEN", "Imports and global code are not step capabilities"
            )
        if isinstance(node, ast.Name) and (
            node.id.startswith("_")
            or node.id
            in {
                "eval",
                "exec",
                "open",
                "compile",
                "globals",
                "locals",
                "getattr",
                "setattr",
                "delattr",
                "input",
                "breakpoint",
                "print",
                "exit",
                "quit",
            }
        ):
            raise TaskError(
                "CONTENT_FORBIDDEN", "Use ctx for external actions and logs"
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise TaskError("CONTENT_FORBIDDEN", "Private attributes are not step API")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "ctx":
                if node.func.attr not in {
                    "call",
                    "result",
                    "output",
                    "log",
                    "cancelled",
                }:
                    raise TaskError("CONTENT_FORBIDDEN", "Unknown ctx operation")
                if (
                    node.func.attr in {"call", "output"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    if node.args[0].value not in capabilities:
                        raise TaskError("CAPABILITY_DENIED", str(node.args[0].value))
                if node.func.attr == "call":
                    action_arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "action_id"), None)
                    if not isinstance(action_arg, ast.Constant) or not isinstance(action_arg.value, str):
                        raise TaskError("CONTENT_FORBIDDEN", "ctx.call requires a literal action_id")
                    if action_arg.value not in capabilities:
                        raise TaskError("CAPABILITY_DENIED", action_arg.value)
    return tree


def pointer(value, path):
    if (
        not isinstance(path, str)
        or (path and not path.startswith("/"))
        or re.search(r"~(?![01])", path)
    ):
        raise TaskError("POINTER_INVALID")
    if not path:
        return value
    for key in path[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise KeyError(key)
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value[key]
            else:
                raise KeyError(key)
        except (KeyError, IndexError) as exc:
            raise TaskError("INPUT_MISSING", f"Missing input at {path}") from exc
    return value


def check_bindings(bindings, preceding):
    if not isinstance(bindings, dict):
        raise TaskError("BINDING_INVALID")
    for binding in bindings.values():
        if not isinstance(binding, dict):
            raise TaskError("BINDING_INVALID")
        if set(binding) == {"literal"}:
            dumps(binding["literal"])
            continue
        if set(binding) != {"ref"} or not isinstance(binding["ref"], dict):
            raise TaskError("BINDING_INVALID")
        ref = binding["ref"]
        if ref.get("source") not in {"task", "step", "environment"}:
            raise TaskError("BINDING_INVALID")
        p = ref.get("pointer")
        if (
            not isinstance(p, str)
            or (p and not p.startswith("/"))
            or re.search(r"~(?![01])", p)
        ):
            raise TaskError("POINTER_INVALID")
        if ref["source"] == "step" and ref.get("step_id") not in preceding:
            raise TaskError(
                "FORWARD_REFERENCE", "References must target preceding steps"
            )


def resolve(bindings, task_inputs, environment, read_output):
    values = {}
    for name, binding in bindings.items():
        if "literal" in binding:
            values[name] = binding["literal"]
        else:
            ref = binding["ref"]
            source = {"task": task_inputs, "environment": environment}.get(
                ref["source"]
            )
            if ref["source"] == "step":
                source = read_output(ref["step_id"], ref.get("output", "data"))
            values[name] = pointer(source, ref["pointer"])
    return values


def automatic_inputs(schema, environment, task_values, overrides=None):
    """Local variables are accessible through inputs; explicit step values win."""
    defaults = {key: spec['default'] for key, spec in schema.get('properties', {}).items() if 'default' in spec}
    values = {**defaults, **environment, **task_values, **(overrides or {})}
    if schema.get('additionalProperties') is False:
        values = {key: value for key, value in values.items() if key in schema.get('properties', {})}
    return values


def normalize_step(document):
    defaults = {
        "name": "Step",
        "goal": "",
        "step_content": "",
        "input_schema": {"type": "object"},
        "output_schema": {},
        "bindings": {},
        "capabilities": [],
        "plugin_requirements": {},
        "timeout_ms": 60000,
        "delay_after_previous_seconds": 0,
        "content_format": "python-async-v1",
    }
    for key in defaults:
        if key in document:
            defaults[key] = document[key]
    if defaults["content_format"] != "python-async-v1":
        raise TaskError("CONTENT_FORMAT_UNSUPPORTED")
    if (
        type(defaults["timeout_ms"]) is not int
        or not 0 < defaults["timeout_ms"] <= 3600000
    ):
        raise TaskError("TIMEOUT_INVALID")
    delay = defaults["delay_after_previous_seconds"]
    if type(delay) is not int or not 0 <= delay <= 86400:
        raise TaskError(
            "STEP_INTERVAL_INVALID",
            "Interval must be an integer from 0 to 86400 seconds",
        )
    defaults["step_content"] = defaults["step_content"].replace("\r\n", "\n")
    if not isinstance(defaults["capabilities"], list) or not all(
        isinstance(x, str) for x in defaults["capabilities"]
    ):
        raise TaskError("CAPABILITY_INVALID")
    defaults["capabilities"] = sorted(set(defaults["capabilities"]))
    check_schema(defaults["input_schema"])
    check_schema(defaults["output_schema"])
    return defaults
