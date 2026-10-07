"""Read-only configured environment observation and explicit secret redaction."""
import json
from taskweave.plugins.sdk import ContextCollection, ContextItem, ContextView, PluginError
from .runner import redact_text


class RedactingContext:
    """Proxy host context, carrying resolved values only within the worker.

    Transport consumers resolve logical refs via ctx.resolve_secret and pass
    those values here; run_command masks them before applying output budgets.
    This is literal value masking, not comprehensive business-data scrubbing.
    """
    def __init__(self, ctx, values):
        self._context = ctx
        self.redaction_values = tuple(getattr(ctx, 'redaction_values', ())) + tuple(value for value in values if value)

    def __getattr__(self, name):
        return getattr(self._context, name)

    def log(self, level, message):
        self._context.log(level, redact_text(message, self.redaction_values))


async def collect_environment(provider_id, ctx, request, *, include_view=True):
    from .actions import ENVIRONMENT_INPUT, inspect_environment
    from jsonschema import Draft202012Validator
    if provider_id != 'process.environment':
        raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')
    request = {} if request is None else request
    if not Draft202012Validator(ENVIRONMENT_INPUT).is_valid(request):
        raise PluginError('PROCESS_CONTEXT_REQUEST_INVALID')
    # Context collection never runs supplied programs/version_args or alters cwd.
    output = await inspect_environment(ctx, request, run_versions=False)
    budget = request.get('max_output_bytes', 65536)
    output.update({'truncated': False, 'omitted_count': 0})
    text = json.dumps(output, ensure_ascii=False)
    # Drop complete observation rows rather than emitting broken JSON or a
    # preview which silently exceeds the model item's byte budget.
    while len(text.encode('utf-8')) > budget:
        target = output['programs'] if output['programs'] else output['directories']
        target.pop()
        output['truncated'] = True
        output['omitted_count'] += 1
        text = json.dumps(output, ensure_ascii=False)
    return ContextCollection([ContextItem('text', 'application/json', text, 'process.environment', output['truncated'])],
        [ContextView('Local process environment', 'json', output)] if include_view else [])
