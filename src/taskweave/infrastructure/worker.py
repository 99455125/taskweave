"""Spawn worker with one event loop and resources retained for a run."""

import asyncio
import importlib
import json
import os
import time

from taskweave.core.ports import Scope, StepResult, ResultRequest, ErrorInfo
from taskweave.core.validation import (
    TaskError,
    SAFE_BUILTINS,
    content_tree,
    validate,
    dumps,
)
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.storage import Results, now, uid


def load_registry(path, home):
    if path is None:
        from taskweave.plugins.manager import PluginManager

        return PluginManager(home).registry(strict=False)
    return load_factory(path)()


def load_factory(path):
    module, name = path.split(":", 1)
    return getattr(importlib.import_module(module), name)


class Resources:
    def __init__(self, registry):
        self.registry, self.items = registry, {}
        self.context = None

    async def acquire(self, provider_id, role):
        key = (provider_id, role)
        if key not in self.items:
            self.items[key] = await self.registry.providers[provider_id].open(
                self.context, role
            )
        return self.items[key]

    def active(self, provider_id):
        return [
            (role, resource)
            for (provider, role), resource in self.items.items()
            if provider == provider_id
        ]

    async def release_all(self):
        for (provider_id, role), resource in list(self.items.items()):
            await self.registry.providers[provider_id].close(resource)
        self.items.clear()


class PluginContext:
    def __init__(
        self, scope, results, resources, environment, secret_refs, cancel, emit
    ):
        self.scope, self.results, self.resources = scope, results, resources
        self.task_parameters = {}
        self.environment, self.secret_refs, self.cancel, self.emit = (
            environment,
            secret_refs,
            cancel,
            emit,
        )

    async def allocate_file(self, name):
        return await self.results.allocate_file(name)

    def resolve_secret(self, reference):
        env_name = self.secret_refs.get(reference)
        if not isinstance(env_name, str) or not env_name.startswith("env:"):
            raise TaskError("SECRET_UNAVAILABLE")
        value = os.getenv(env_name[4:])
        if value is None:
            raise TaskError("SECRET_UNAVAILABLE")
        return value

    def log(self, level, message):
        self.emit("Log", {"level": level, "message": redact(message)})

    def cancelled(self):
        return self.cancel.is_set()


class StepContext:
    def __init__(self, step, plugin_ctx, registry):
        self.step, self.context, self.registry = step, plugin_ctx, registry
        self.scope = plugin_ctx.scope
        self.effect = "NOT_STARTED"
        self.phase = "preflight"
        self.action_index = 0

    async def call(self, action_id, inputs):
        if self.cancelled():
            raise TaskError("CANCELLED")
        if action_id not in self.step["capabilities"]:
            raise TaskError("CAPABILITY_DENIED")
        action = self.registry.actions.get(action_id)
        if action is None:
            raise TaskError("CAPABILITY_UNAVAILABLE")
        self.action_index += 1
        action_index = self.action_index
        metadata = {'action_id': action_id, 'action_index': action_index, 'effect': action.spec.effect}
        metadata.update({key: redact(inputs[key]) for key in ('selector', 'role') if key in inputs})
        started = time.monotonic()
        self.context.emit('ActionStarted', metadata)
        try:
            self.phase = "preflight"
            validate(inputs, action.spec.input_schema)
            diagnostics = await action.preflight(self.context, inputs)
            if any(x.severity == "error" for x in diagnostics):
                raise TaskError("PREFLIGHT_FAILED")
            self.phase = "execute"
            if action.spec.effect == "WRITE":
                self.effect = "UNKNOWN"
            output = await asyncio.wait_for(action.execute(self.context, inputs), action.spec.timeout_ms / 1000)
            validate(output, action.spec.output_schema)
            self.phase = "verify"
            diagnostics = await action.verify(self.context, inputs, output)
            if any(x.severity == "error" for x in diagnostics):
                raise TaskError("VERIFY_FAILED")
            self.context.emit('ActionObserved', {**metadata, 'elapsed_ms': round((time.monotonic()-started)*1000)})
            return output
        except Exception as exc:
            self.context.emit('ActionFailed', {**metadata, 'phase': self.phase, 'error_code': getattr(exc, 'code', type(exc).__name__), 'elapsed_ms': round((time.monotonic()-started)*1000)})
            raise

    def result(self, data=None, outputs=(), views=()):
        from taskweave.core.result_views import validate_views
        validate_views(data, views, self.registry.views)
        return StepResult(data, outputs, views)

    def output(self, handler_id, name, payload):
        if handler_id not in self.step["capabilities"]:
            raise TaskError("CAPABILITY_DENIED")
        return ResultRequest(handler_id, name, payload)

    def log(self, message):
        self.context.log("INFO", message)

    def cancelled(self):
        return self.context.cancelled()


def worker_main(connection, cancellation, home, factory, parent_pid):
    # Pipe EOF stops an idle orphan; active steps also watch the parent process.
    import threading

    def watch_parent():
        while True:
            time.sleep(0.2)
            if os.getppid() != parent_pid:
                os._exit(72)

    threading.Thread(target=watch_parent, daemon=True).start()
    registry = load_registry(factory, home)
    resources = Resources(registry)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        while True:
            try:
                message = json.loads(connection.recv())
            except EOFError:
                break
            if message["kind"] == "close":
                break
            scope = Scope(**message["scope"])
            seq = 0

            def emit(kind, payload):
                nonlocal seq
                seq += 1
                connection.send(
                    dumps(
                        {
                            "event_id": uid(),
                            "attempt_id": scope.attempt_id,
                            "run_id": scope.run_id,
                            "kind": kind,
                            "seq": seq,
                            "timestamp": now(),
                            "payload": payload,
                        }
                    )
                )

            results = Results(home, scope, registry)
            pc = PluginContext(
                scope,
                results,
                resources,
                message["environment"],
                message["secret_refs"],
                cancellation,
                emit,
            )
            pc.task_parameters = message.get('task_parameters', {})
            resources.context = pc
            ctx = StepContext(message["step"], pc, registry)

            async def execute():
                async def heartbeat():
                    while True:
                        emit("Heartbeat", {})
                        await asyncio.sleep(2)

                beat = asyncio.create_task(heartbeat())
                try:
                    registry.check(message["step"])
                    tree = content_tree(
                        message["step"]["step_content"], message["step"]["capabilities"]
                    )
                    ns = {"__builtins__": SAFE_BUILTINS}
                    exec(compile(tree, "<step>", "exec"), ns)
                    if message["kind"] == "context":
                        provider_id = message["provider_id"]
                        plugin = next(
                            (
                                p
                                for p in registry.selected_plugins(
                                    message["step"]["capabilities"]
                                )
                                if provider_id
                                in p.authoring(
                                    message["step"]["capabilities"]
                                ).context_provider_ids
                            ),
                            None,
                        )
                        if plugin is None:
                            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE")
                        from dataclasses import asdict

                        items = await plugin.collect_context(
                            provider_id, pc, message.get("request", {})
                        )
                        emit(
                            "ContextCompleted",
                            {"items": redact([asdict(c) for c in items])},
                        )
                        return
                    validate(message["inputs"], message["step"]["input_schema"])
                    result = await ns["run"](ctx, message["inputs"])
                    if not isinstance(result, StepResult):
                        raise TaskError("RESULT_INVALID", "Return ctx.result(...)")
                    ctx.phase = "verify"
                    validate(result.data, message["step"]["output_schema"])
                    ctx.effect = "SUCCEEDED"
                    ctx.phase = "persist"
                    refs = results.persist(result)
                    emit("AttemptCompleted", {"refs": refs})
                    results.cleanup_staging()
                except Exception as exc:
                    code = (
                        exc.code if isinstance(exc, TaskError) else type(exc).__name__
                    )
                    if ctx.phase == "persist":
                        code = "RESULT_SAVE_FAILED"
                    diagnostic_refs = []
                    for plugin in registry.selected_plugins(
                        message["step"]["capabilities"]
                    ):
                        hook = getattr(plugin, "failure_results", None)
                        if (
                            hook
                            and ctx.phase != "persist"
                            and message["kind"] != "context"
                        ):
                            try:
                                requests = await asyncio.wait_for(
                                    hook(
                                        pc,
                                        ErrorInfo(
                                            code, str(exc), ctx.phase, ctx.effect
                                        ),
                                    ),
                                    5,
                                )
                                if requests:
                                    diagnostic_refs.extend(
                                        results.persist_diagnostics(requests)
                                    )
                            except Exception as diagnostic_error:
                                pc.log(
                                    "WARNING",
                                    "Diagnostic artifact capture failed: "
                                    + type(diagnostic_error).__name__,
                                )
                    emit(
                        "AttemptFailed",
                        {
                            "refs": diagnostic_refs,
                            "code": code,
                            "phase": ctx.phase,
                            "effect_state": ctx.effect,
                            "message": redact(str(exc))[:4096],
                        },
                    )
                finally:
                    beat.cancel()
                    await asyncio.gather(beat, return_exceptions=True)

            loop.run_until_complete(execute())
    finally:
        try:
            loop.run_until_complete(resources.release_all())
        finally:
            loop.close()
            connection.close()
