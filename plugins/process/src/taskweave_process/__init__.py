"""Resource-free local process plugin and reusable process/artifact libraries."""
from dataclasses import replace
from taskweave.plugins.sdk import AuthoringContribution
from .actions import CheckEnvironment, CollectArtifacts, ENVIRONMENT_INPUT, Run
from .artifacts import CommandFailureResultHandler, FileResultHandler, stage_artifact
from .context import RedactingContext, collect_environment
from .runner import CommandFailureEvidence, ProcessError, run_command
from .session import OwnedProcessSession

__all__ = ['ProcessPlugin', 'ProcessError', 'run_command', 'stage_artifact', 'FileResultHandler',
           'RedactingContext', 'CommandFailureEvidence', 'CommandFailureResultHandler', 'OwnedProcessSession']


class ProcessPlugin:
    def __init__(self):
        self._failure_evidence = CommandFailureEvidence('process.command_failure', 'process_command_failure')

    def manifest(self):
        return {'id': 'process', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1',
                'dependencies': {}, 'config_variables': [{'key': 'process_root', 'type': 'string', 'required': True,
                'description': 'Explicit local root for working directories and collected files; task parameters override environment'}],
                'context_requests': {'process.environment': ENVIRONMENT_INPUT}}

    def actions(self):
        return {'process.check_environment': CheckEnvironment(), 'process.run': Run(self._failure_evidence), 'process.collect_artifacts': CollectArtifacts()}

    def tools(self):
        return {'process.inspect_environment': CheckEnvironmentTool()}

    def result_handlers(self):
        return {'process.file': FileResultHandler(), 'process.command_failure': CommandFailureResultHandler()}

    def resource_providers(self):
        return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            'Use literal executable and args; shell syntax is not evaluated. Configure process_root explicitly. '
            'process.run is WRITE and never automatically retried. Inspect exit_code even when the action returns. '
            'Default timeout is 60 seconds (1–1800), output per stream 65536 bytes (1024–1048576); truncation is explicit. '
            'env_secret_refs maps child environment names to logical secret references, stdin_secret_ref resolves stdin; '
            'do not place credentials in argv or ordinary env/stdin. No command output or argv is logged by default. '
            'process.collect_artifacts defaults to 16 MiB file/aggregate budgets (up to 64 MiB), rejects oversize files, '
            'and returns token metadata, not local paths. Saving requires ctx.output("process.file", name, artifact) '
            'and ctx.result(outputs=...). Cancellation/timeout can leave business side effects unknown. '
            'Started command cancellation/timeout retains bounded redacted partial output as process.command_failure diagnostics; '
            'diagnostics do not make a failed attempt successful or available as step business output. '
            'The process.environment context and process.inspect_environment tool only check paths/executables and never run commands.',
            examples=('''async def run(ctx, inputs):
    execution = await ctx.call("process.run", {"executable": inputs["executable"], "args": inputs["args"]})
    return ctx.result(data=execution)''',
            '''async def run(ctx, inputs):
    collected = await ctx.call("process.collect_artifacts", {"paths": [inputs["report_path"]]})
    artifact = collected["artifacts"][0]
    return ctx.result(data=collected, outputs=[ctx.output("process.file", "report", artifact)])'''),
            context_provider_ids=('process.environment',), tool_ids=('process.inspect_environment',),
            constraints={'content_format': 'python-async-v1'})

    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        return await collect_environment(provider_id, ctx, request, include_view=include_view)

    async def lint(self, step_document):
        return []

    async def diagnose(self, error, refs):
        return []

    async def failure_results(self, ctx, error):
        return await self._failure_evidence.failure_results(ctx, error)


class CheckEnvironmentTool(CheckEnvironment):
    """Authoring tool performs passive checks only, unlike explicit version action."""
    spec = replace(CheckEnvironment.spec, id='process.inspect_environment',
                   description='Observe executable/directory availability without executing programs', timeout_ms=60000)

    async def execute(self, ctx, inputs):
        from .actions import inspect_environment
        return await inspect_environment(ctx, inputs, run_versions=False)
