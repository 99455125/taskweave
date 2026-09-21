"""Discover installed entry points; load only explicitly enabled factories."""

from importlib.metadata import entry_points
import json
from pathlib import Path
from taskweave.core.validation import TaskError, dumps
from taskweave.plugins.registry import Registry


class PluginManager:
    def __init__(self, home, entries=None):
        self.path = Path(home) / "plugins.json"
        self.entries = list(
            entries if entries is not None else entry_points(group="taskweave.plugins")
        )

    def enabled(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text())
        if data.get("format") != 1 or not isinstance(data.get("enabled"), list):
            raise TaskError("PLUGIN_CONFIG_INVALID")
        if not all(isinstance(n, str) for n in data["enabled"]) or len(
            set(data["enabled"])
        ) != len(data["enabled"]):
            raise TaskError("PLUGIN_CONFIG_INVALID")
        return [name for name in data["enabled"] if name not in {"demo", "sample", "text"}]

    def registry(self, enabled=None, strict=True):
        enabled = self.enabled() if enabled is None else enabled
        plugins, errors = [], {}
        for name in enabled:
            matches = [e for e in self.entries if e.name == name]
            try:
                if len(matches) != 1:
                    raise TaskError(
                        "PLUGIN_DISCOVERY_CONFLICT"
                        if matches
                        else "PLUGIN_NOT_INSTALLED",
                        name,
                    )
                try:
                    plugin = matches[0].load()()
                except Exception as exc:
                    raise TaskError("PLUGIN_LOAD_FAILED", name) from exc
                if plugin.manifest().get("id") != name:
                    raise TaskError("PLUGIN_ID_MISMATCH", name)
                # Validate each plugin while allowing its dependencies to be resolved below.
                plugins.append(plugin)
            except TaskError as exc:
                if strict:
                    raise
                errors[name] = exc.code
        if strict:
            return Registry(plugins)
        # Keep unaffected plugins usable if an enabled package is missing or incompatible.
        while True:
            try:
                registry = Registry(plugins)
                registry.load_errors = errors
                return registry
            except TaskError as exc:
                affected = str(exc)
                removals = [
                    p
                    for p in plugins
                    if p.manifest().get("id") == affected
                    or affected in p.manifest().get("dependencies", {})
                ]
                if not removals:
                    # Identify a malformed single plugin without dropping healthy packages.
                    for plugin in plugins:
                        try:
                            Registry([plugin])
                        except TaskError as individual:
                            if individual.code != "PLUGIN_DEPENDENCY_MISSING":
                                removals.append(plugin)
                    if not removals:
                        removals = list(
                            plugins
                        )  # Cyclic/cross-plugin conflicts are explicit errors.
                if not removals:
                    raise
                for plugin in removals:
                    errors[plugin.manifest().get("id", "unknown")] = exc.code
                    plugins.remove(plugin)

    def configure(self, plugin_id, enabled):
        if type(enabled) is not bool:
            raise TaskError("PLUGIN_CONFIG_INVALID")
        names = self.enabled()
        names = (
            sorted(set(names + [plugin_id]))
            if enabled
            else [n for n in names if n != plugin_id]
        )
        registry = self.registry(names)  # Validate before changing configuration.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(dumps({"format": 1, "enabled": names}))
        temporary.replace(self.path)
        return registry

    def catalog(self):
        enabled = self.enabled()
        records = [
            {
                "id": e.name,
                "entry_point": e.value,
                "distribution": e.dist.name if e.dist else None,
                "enabled": e.name in enabled,
            }
            for e in self.entries
        ]
        discovered = {e.name for e in self.entries}
        records.extend(
            {
                "id": name,
                "enabled": True,
                "entry_point": None,
                "distribution": None,
                "error": "PLUGIN_NOT_INSTALLED",
            }
            for name in enabled
            if name not in discovered
        )
        return records
