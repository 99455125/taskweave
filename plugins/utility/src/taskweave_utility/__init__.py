"""Basic data operations for TaskWeave steps; no arbitrary Python execution."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
import re
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError


DECIMAL_TEXT = r"^-?[0-9]{1,30}(?:\.[0-9]{1,18})?$"
DECIMAL_RESULT = r"^-?[0-9]{1,64}(?:\.[0-9]{1,12})?$"
ROUNDING = {"HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN, "DOWN": ROUND_DOWN}


class Now:
    spec = CapabilitySpec(
        "utility.now", "读取当前时间并按指定时区返回 ISO 时间与秒级编号片段",
        {"type": "object", "properties": {"timezone": {"type": "string", "minLength": 1, "maxLength": 64}}, "additionalProperties": False},
        {"type": "object", "properties": {
            "iso": {"type": "string"}, "compact": {"type": "string", "pattern": "^[0-9]{14}$"}, "timezone": {"type": "string"},
        }, "required": ["iso", "compact", "timezone"], "additionalProperties": False},
        "READ", retry_safe=False,
    )

    async def preflight(self, ctx, inputs): return []

    async def execute(self, ctx, inputs):
        name = inputs.get("timezone", "UTC")
        try:
            zone = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise PluginError("UTILITY_TIMEZONE_INVALID", f"无效时区：{name}") from exc
        current = datetime.now(zone)
        return {"iso": current.isoformat(timespec="seconds"), "compact": current.strftime("%Y%m%d%H%M%S"), "timezone": name}

    async def verify(self, ctx, inputs, output): return []


class Uuid:
    spec = CapabilitySpec(
        "utility.uuid", "生成 UUID v4 标识",
        {"type": "object", "properties": {}, "additionalProperties": False},
        {"type": "object", "properties": {"value": {"type": "string", "format": "uuid"}}, "required": ["value"], "additionalProperties": False},
        "READ", retry_safe=False,
    )

    async def preflight(self, ctx, inputs): return []
    async def execute(self, ctx, inputs): return {"value": str(uuid4())}
    async def verify(self, ctx, inputs, output): return []


class DecimalCalculate:
    spec = CapabilitySpec(
        "utility.decimal", "精确十进制四则运算，按指定小数位舍入并返回字符串",
        {"type": "object", "properties": {
            "operation": {"enum": ["add", "subtract", "multiply", "divide"]},
            "left": {"type": "string", "pattern": DECIMAL_TEXT},
            "right": {"type": "string", "pattern": DECIMAL_TEXT},
            "scale": {"type": "integer", "minimum": 0, "maximum": 12},
            "rounding": {"enum": list(ROUNDING)},
        }, "required": ["operation", "left", "right", "scale"], "additionalProperties": False},
        {"type": "object", "properties": {"value": {"type": "string", "pattern": DECIMAL_RESULT}}, "required": ["value"], "additionalProperties": False},
        "READ", retry_safe=True,
    )

    async def preflight(self, ctx, inputs): return []

    async def execute(self, ctx, inputs):
        left, right = inputs.get("left"), inputs.get("right")
        if not all(isinstance(value, str) and re.fullmatch(DECIMAL_TEXT, value) for value in (left, right)):
            raise PluginError("UTILITY_NUMBER_INVALID", "十进制操作数必须是数字字符串")
        operation = inputs.get("operation")
        scale = inputs.get("scale")
        rounding = inputs.get("rounding", "HALF_UP")
        if operation not in {"add", "subtract", "multiply", "divide"} or type(scale) is not int or not 0 <= scale <= 12 or rounding not in ROUNDING:
            raise PluginError("UTILITY_CALCULATION_INVALID", "运算、精度或舍入方式无效")
        a, b = Decimal(left), Decimal(right)
        if operation == "divide" and b == 0:
            raise PluginError("UTILITY_DIVISION_BY_ZERO", "除数不能为零")
        try:
            with localcontext() as context:
                context.prec = 80
                value = {
                    "add": lambda: a + b,
                    "subtract": lambda: a - b,
                    "multiply": lambda: a * b,
                    "divide": lambda: a / b,
                }[operation]()
                value = value.quantize(Decimal(1).scaleb(-scale), rounding=ROUNDING[rounding])
        except InvalidOperation as exc:
            raise PluginError("UTILITY_CALCULATION_INVALID", "计算结果超出支持范围") from exc
        return {"value": format(value, "f")}

    async def verify(self, ctx, inputs, output): return []


class UtilityPlugin:
    def manifest(self):
        return {"id": "utility", "api_version": 1, "package_version": "0.1.0", "core_requires": ">=0.1,<1", "dependencies": {}, "resource_descriptions": {}, "config_variables": []}

    def actions(self):
        return {"utility.now": Now(), "utility.uuid": Uuid(), "utility.decimal": DecimalCalculate()}

    def tools(self): return {}
    def resource_providers(self): return {}
    def result_handlers(self): return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            "仅在步骤需要当前时间、UUID 或精确十进制计算时使用 utility 能力。utility.now 可传 timezone（默认 UTC），返回 iso、compact（YYYYMMDDHHMMSS）和 timezone；utility.uuid 返回 value；utility.decimal 接收 operation、left/right 数字字符串、scale，以及可选 rounding（HALF_UP 默认、HALF_EVEN、DOWN），返回字符串 value。普通运算和字符串拼接直接在步骤代码完成。时间与 UUID 每次调用可变，若作为业务编号或后续依赖，需把实际返回值写入 ctx.result(data=...)；不要写死或推测。",
            constraints={"content_format": "python-async-v1"},
        )

    async def lint(self, step_document): return []
    async def diagnose(self, error, refs): return []
