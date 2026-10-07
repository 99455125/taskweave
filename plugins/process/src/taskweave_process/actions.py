"""Structured process/environment/artifact actions; no cross-plugin calls."""
import asyncio
import shutil

from taskweave.plugins.sdk import CapabilitySpec, PluginError
from .artifacts import ARTIFACT_SCHEMA, DEFAULT_TRANSFER_BYTES, MAX_TRANSFER_BYTES, _stage_bytes, confined_path, read_artifact, validate_transfer_limit
from .runner import ProcessError, run_command, validate_limits


def object_schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
ARGUMENTS = {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 1000}
STRINGS = {'type': 'object', 'additionalProperties': {'type': 'string'}}
TIMEOUT = {'type': 'integer', 'minimum': 1, 'maximum': 1800, 'default': 60}
OUTPUT_BYTES = {'type': 'integer', 'minimum': 1024, 'maximum': 1048576, 'default': 65536}
TRANSFER_BYTES = {'type': 'integer', 'minimum': 1, 'maximum': MAX_TRANSFER_BYTES, 'default': DEFAULT_TRANSFER_BYTES}
COMMAND_SCHEMA = object_schema({
    'exit_code': {'type': ['integer', 'null']}, 'stdout': {'type': 'string'}, 'stderr': {'type': 'string'},
    'stdout_truncated': {'type': 'boolean'}, 'stderr_truncated': {'type': 'boolean'},
    'duration_ms': {'type': 'integer', 'minimum': 0}},
    ['exit_code', 'stdout', 'stderr', 'stdout_truncated', 'stderr_truncated', 'duration_ms'])
PROGRAM_SCHEMA = object_schema({'executable': TEXT, 'version_args': ARGUMENTS}, ['executable'])
ENVIRONMENT_INPUT = object_schema({
    'programs': {'type': 'array', 'items': PROGRAM_SCHEMA, 'maxItems': 32},
    'directories': {'type': 'array', 'items': TEXT, 'maxItems': 32},
    'timeout_seconds': TIMEOUT, 'max_output_bytes': OUTPUT_BYTES})
PROGRAM_RESULT = object_schema({'executable': TEXT, 'available': {'type': 'boolean'},
    'error_code': {'type': ['string', 'null']}, 'version': {'anyOf': [COMMAND_SCHEMA, {'type': 'null'}]}},
    ['executable', 'available', 'error_code', 'version'])
DIRECTORY_RESULT = object_schema({'path': TEXT, 'available': {'type': 'boolean'}, 'error_code': {'type': ['string', 'null']}},
    ['path', 'available', 'error_code'])
ENVIRONMENT_OUTPUT = object_schema({'programs': {'type': 'array', 'items': PROGRAM_RESULT},
    'directories': {'type': 'array', 'items': DIRECTORY_RESULT}}, ['programs', 'directories'])


def process_root(ctx):
    values = {**ctx.environment, **ctx.task_parameters}
    root = values.get('process_root')
    if not isinstance(root, str) or not root.strip():
        raise PluginError('PROCESS_ROOT_REQUIRED', 'Configure process_root in environment or task parameters')
    _, resolved = confined_path(root, '.', directory=True)
    return str(resolved)


def command_directory(ctx, inputs):
    root = process_root(ctx)
    _, directory = confined_path(root, inputs.get('cwd', '.'), directory=True)
    return str(directory)


class Run:
    def __init__(self, failure_evidence=None):
        self.failure_evidence = failure_evidence

    spec = CapabilitySpec('process.run', 'Execute literal executable/argv within process_root; no shell or automatic retry',
        object_schema({'executable': TEXT, 'args': ARGUMENTS, 'cwd': TEXT, 'env': STRINGS,
            'env_secret_refs': {'type': 'object', 'additionalProperties': TEXT}, 'stdin': {'type': 'string'},
            'stdin_secret_ref': TEXT, 'timeout_seconds': TIMEOUT, 'max_output_bytes': OUTPUT_BYTES}, ['executable']),
        COMMAND_SCHEMA, 'WRITE', timeout_ms=1810000, retry_safe=False)

    async def preflight(self, ctx, inputs):
        command_directory(ctx, inputs)
        validate_limits(inputs.get('timeout_seconds', 60), inputs.get('max_output_bytes', 65536))
        if 'stdin' in inputs and 'stdin_secret_ref' in inputs:
            raise PluginError('PROCESS_STDIN_INVALID', 'Select stdin or stdin_secret_ref')
        return []

    async def execute(self, ctx, inputs):
        from .context import RedactingContext
        await self.preflight(ctx, inputs)
        if ctx.cancelled():
            raise ProcessError('CANCELLED')
        env = dict(inputs.get('env', {}))
        secrets = []
        for variable, reference in inputs.get('env_secret_refs', {}).items():
            secret = ctx.resolve_secret(reference)
            env[variable] = secret
            secrets.append(secret)
        stdin = inputs.get('stdin')
        if 'stdin_secret_ref' in inputs:
            stdin = ctx.resolve_secret(inputs['stdin_secret_ref'])
            secrets.append(stdin)
        safe = RedactingContext(ctx, secrets)
        command = run_command if self.failure_evidence is None else self.failure_evidence.run_command
        positional = [safe] if self.failure_evidence is None else [safe, 'process.run']
        return await command(*positional, inputs['executable'], list(inputs.get('args', [])),
            cwd=command_directory(ctx, inputs), env=env, stdin=None if stdin is None else stdin.encode('utf-8'),
            timeout_seconds=inputs.get('timeout_seconds', 60), max_output_bytes=inputs.get('max_output_bytes', 65536))

    async def verify(self, ctx, inputs, output):
        return []  # Nonzero exit is data; business callers must inspect exit_code.


async def inspect_environment(ctx, inputs, *, run_versions=True):
    root = process_root(ctx)
    programs, directories = inputs.get('programs', []), inputs.get('directories', [])
    if len(programs) > 32 or len(directories) > 32:
        raise PluginError('PROCESS_OBSERVATION_LIMIT_INVALID')
    timeout, budget = inputs.get('timeout_seconds', 60), inputs.get('max_output_bytes', 65536)
    validate_limits(timeout, budget)
    output = {'programs': [], 'directories': []}
    for program in programs:
        if ctx.cancelled():
            raise ProcessError('CANCELLED')
        executable = program['executable']
        # Relative configured executables are resolved against process_root.
        candidate = executable
        if '/' in executable or '\\' in executable:
            from pathlib import Path
            candidate = str((Path(root) / executable).resolve())
        available = shutil.which(candidate) is not None
        item = {'executable': executable, 'available': available,
                'error_code': None if available else 'PROCESS_EXECUTABLE_NOT_FOUND', 'version': None}
        if available and run_versions and 'version_args' in program:
            try:
                item['version'] = await run_command(ctx, candidate, list(program['version_args']), cwd=root,
                    env={}, stdin=None, timeout_seconds=timeout, max_output_bytes=budget)
                if item['version']['exit_code'] != 0:
                    item['error_code'] = 'PROCESS_VERSION_CHECK_FAILED'
            except ProcessError as exc:
                if exc.code == 'CANCELLED':
                    raise
                item['error_code'], item['version'] = exc.code, exc.result
        output['programs'].append(item)
    for path in directories:
        if ctx.cancelled():
            raise ProcessError('CANCELLED')
        try:
            confined_path(root, path, directory=True)
            item = {'path': path, 'available': True, 'error_code': None}
        except PluginError as exc:
            item = {'path': path, 'available': False, 'error_code': exc.code}
        output['directories'].append(item)
    return output


class CheckEnvironment:
    # Up to 32 explicit version checks, each with the configured timeout.
    spec = CapabilitySpec('process.check_environment', 'Inspect specified executables, explicit version commands and root-confined directories',
        ENVIRONMENT_INPUT, ENVIRONMENT_OUTPUT, 'READ', timeout_ms=57610000, retry_safe=True)

    async def preflight(self, ctx, inputs):
        process_root(ctx)
        return []

    async def execute(self, ctx, inputs):
        return await inspect_environment(ctx, inputs)

    async def verify(self, ctx, inputs, output):
        return []


class CollectArtifacts:
    spec = CapabilitySpec('process.collect_artifacts', 'Stage complete files inside process_root; persist using process.file outputs',
        object_schema({'paths': {'type': 'array', 'items': TEXT, 'minItems': 1, 'maxItems': 100},
            'max_bytes': TRANSFER_BYTES, 'max_total_bytes': TRANSFER_BYTES}, ['paths']),
        object_schema({'artifacts': {'type': 'array', 'items': ARTIFACT_SCHEMA}, 'total_bytes': {'type': 'integer', 'minimum': 0}},
            ['artifacts', 'total_bytes']), 'READ', timeout_ms=60000, retry_safe=True)

    async def preflight(self, ctx, inputs):
        root = process_root(ctx)
        maximum, aggregate = inputs.get('max_bytes', DEFAULT_TRANSFER_BYTES), inputs.get('max_total_bytes', DEFAULT_TRANSFER_BYTES)
        validate_transfer_limit(maximum)
        validate_transfer_limit(aggregate)
        paths = inputs['paths']
        if not 1 <= len(paths) <= 100:
            raise PluginError('PROCESS_ARTIFACT_COUNT_INVALID')
        total = 0
        for path in paths:
            _, source = confined_path(root, path)
            size = source.stat().st_size
            if size > maximum:
                raise PluginError('PROCESS_ARTIFACT_TOO_LARGE')
            total += size
        if total > aggregate:
            raise PluginError('PROCESS_ARTIFACT_TOO_LARGE', 'Aggregate transfer budget exceeded')
        return []

    async def execute(self, ctx, inputs):
        await self.preflight(ctx, inputs)
        output = {'artifacts': [], 'total_bytes': 0}
        aggregate = inputs.get('max_total_bytes', DEFAULT_TRANSFER_BYTES)
        for path in inputs['paths']:
            remaining = aggregate - output['total_bytes']
            try:
                name, data = await asyncio.to_thread(read_artifact, process_root(ctx), path,
                    max(1, min(inputs.get('max_bytes', DEFAULT_TRANSFER_BYTES), remaining)))
            except OSError as exc:
                raise PluginError('PROCESS_ARTIFACT_READ_FAILED') from exc
            if len(data) > remaining:
                raise PluginError('PROCESS_ARTIFACT_TOO_LARGE')
            artifact = await _stage_bytes(ctx, name, data)
            output['artifacts'].append(artifact)
            output['total_bytes'] += artifact['size_bytes']
        return output

    async def verify(self, ctx, inputs, output):
        return []
