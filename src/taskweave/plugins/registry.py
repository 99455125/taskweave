"""Validated registry shared by authoring and fixed execution."""

from dataclasses import asdict
import re
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion
from taskweave import __version__
from taskweave.core.validation import TaskError, check_schema


class Registry:
    def __init__(self, plugins=()):
        self.plugins = list(plugins)
        self.actions, self.tools, self.handlers, self.providers = {}, {}, {}, {}
        from taskweave.core.result_views import BUILTIN_VIEWS
        self.views = dict(BUILTIN_VIEWS)
        self.versions, self.manifests = {}, {}
        self.load_errors = {}
        for plugin in self.plugins:
            m = plugin.manifest()
            name = m.get("id", "")
            if (
                not re.fullmatch(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*", name)
                or name in self.versions
            ):
                raise TaskError("PLUGIN_CONFLICT", name)
            if m.get("api_version") != 1:
                raise TaskError("PLUGIN_API_INCOMPATIBLE", name)
            try:
                Version(m["package_version"])
                if Version(__version__) not in SpecifierSet(
                    m.get("core_requires", ">=0.1,<1")
                ):
                    raise TaskError("PLUGIN_CORE_INCOMPATIBLE", name)
            except (InvalidVersion, InvalidSpecifier, KeyError) as exc:
                raise TaskError("PLUGIN_MANIFEST_INVALID", name) from exc
            self.versions[name] = m["package_version"]
            self.manifests[name] = m
            for vid, descriptor in getattr(plugin, 'result_views', lambda: {})().items():
                if vid in self.views or not vid.startswith(name + '.') or not isinstance(descriptor, dict) or descriptor.get('type') not in {'json', 'table', 'image', 'report'}:
                    raise TaskError('RESULT_VIEW_INVALID', vid)
                self.views[vid] = descriptor

            for target, source in [
                (self.actions, plugin.actions()),
                (self.tools, plugin.tools()),
                (self.handlers, plugin.result_handlers()),
                (self.providers, plugin.resource_providers()),
            ]:
                for cid, value in source.items():
                    if cid in target or not cid.startswith(name + "."):
                        raise TaskError("CAPABILITY_CONFLICT", cid)
                    if target is self.actions or target is self.tools:
                        if (
                            value.spec.id != cid
                            or value.spec.effect not in {"READ", "WRITE"}
                            or value.spec.timeout_ms <= 0
                        ):
                            raise TaskError("CAPABILITY_SPEC_INVALID", cid)
                        check_schema(value.spec.input_schema)
                        check_schema(value.spec.output_schema)
                    target[cid] = value
        visited, active = set(), set()

        def visit(name):
            if name in active:
                raise TaskError("PLUGIN_DEPENDENCY_CYCLE", name)
            if name in visited:
                return
            active.add(name)
            for dependency, requirement in (
                self.manifests[name].get("dependencies", {}).items()
            ):
                try:
                    compatible = dependency in self.versions and Version(
                        self.versions[dependency]
                    ) in SpecifierSet(requirement)
                except InvalidSpecifier as exc:
                    raise TaskError("PLUGIN_MANIFEST_INVALID", name) from exc
                if not compatible:
                    raise TaskError("PLUGIN_DEPENDENCY_MISSING", dependency)
                visit(dependency)
            active.remove(name)
            visited.add(name)

        for name in self.versions:
            visit(name)
        for action in list(self.actions.values()) + list(self.tools.values()):
            if set(action.spec.resource_ids) - set(self.providers):
                raise TaskError("RESOURCE_PROVIDER_UNAVAILABLE", action.spec.id)

    def check(self, step):
        available = (
            set(self.actions)
            | set(self.tools)
            | set(self.handlers)
            | set(self.providers)
        )
        if set(step["capabilities"]) - available:
            raise TaskError(
                "CAPABILITY_UNAVAILABLE",
                ", ".join(sorted(set(step["capabilities"]) - available)),
            )
        for name, version in step["plugin_requirements"].items():
            try:
                matches = (
                    self.versions.get(name) == version
                    if not any(c in version for c in "<>=!~")
                    else name in self.versions
                    and Version(self.versions[name]) in SpecifierSet(version)
                )
            except InvalidSpecifier as exc:
                raise TaskError("PLUGIN_VERSION_MISMATCH") from exc
            if not matches:
                raise TaskError("PLUGIN_VERSION_MISMATCH")

    def contributions(self, capabilities):
        contributions = [
            p.authoring(capabilities) for p in self.selected_plugins(capabilities)
        ]
        constraints = {}
        for c in contributions:
            for key, value in c.constraints.items():
                if (
                    key in {"entrypoint", "content_format"}
                    and value
                    != {
                        "entrypoint": "async def run(ctx, inputs)",
                        "content_format": "python-async-v1",
                    }[key]
                ):
                    raise TaskError("AUTHORING_CONSTRAINT_CONFLICT", key)
                if key in constraints and constraints[key] != value:
                    raise TaskError("AUTHORING_CONSTRAINT_CONFLICT", key)
                constraints[key] = value
        return contributions

    def catalog(self):
        return {
            "load_errors": self.load_errors,
            "versions": self.versions,
            "actions": [asdict(x.spec) for x in self.actions.values()],
            "tools": [asdict(x.spec) for x in self.tools.values()],
            "result_handlers": list(self.handlers),
            "result_views": self.views,
            "resource_providers": list(self.providers),
            "manifests": self.manifests,
        }

    def selected_plugins(self, capabilities):
        return [
            p
            for p in sorted(self.plugins, key=lambda p: p.manifest()["id"])
            if any(c.startswith(p.manifest()["id"] + ".") for c in capabilities)
        ]
