"""Select explicit, module-scoped unittest targets from product source paths."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path


class UnmappedSourceError(ValueError):
    """A changed product source file has no explicit test module mapping."""


TARGET_PATTERN = re.compile(r"^tests(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
PRODUCT_ROOTS = ("src/taskweave", "plugins")


def _check_target(target: str) -> bool:
    return bool(TARGET_PATTERN.fullmatch(target))


def _validate_graph(modules):
    for name, record in modules.items():
        if not isinstance(record, dict):
            raise ValueError(f"module {name!r} must be an object")
        for key in ("source_globs", "targets", "depends_on", "browser_targets"):
            if not isinstance(record.get(key), list):
                raise ValueError(f"module {name!r} must provide list {key!r}")
        if not record["source_globs"] or not record["targets"]:
            raise ValueError(f"module {name!r} needs source_globs and explicit targets")
        if any(not isinstance(pattern, str) or not pattern for pattern in record["source_globs"]):
            raise ValueError(f"module {name!r} source_globs must contain non-empty strings")
        for dependency in record["depends_on"]:
            if dependency not in modules:
                raise ValueError(f"module {name!r} depends on unknown module {dependency!r}")
        for key in ("targets", "browser_targets"):
            for target in record[key]:
                if not isinstance(target, str) or not _check_target(target):
                    raise ValueError(f"invalid unittest target {target!r} in {name!r}.{key}")

    visiting, visited = set(), set()
    def visit(name):
        if name in visiting:
            raise ValueError(f"module dependency cycle includes {name!r}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in modules[name]["depends_on"]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
    for name in modules:
        visit(name)


def load_map(map_path: Path, root: Path):
    data = json.loads(Path(map_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("modules"), dict):
        raise ValueError("module map must have version=1 and a modules object")
    modules = OrderedDict(data["modules"].items())
    _validate_graph(modules)
    return modules


def _relative_changed(path, root: Path):
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix(), candidate
    except ValueError:
        raise UnmappedSourceError(f"changed path is outside repository root: {path}") from None


def _product_path(relative: str):
    return relative.startswith(PRODUCT_ROOTS)


def _source_files_for_path(relative: str, candidate: Path, root: Path):
    if candidate.is_dir():
        return [file.relative_to(root).as_posix() for file in sorted(candidate.rglob("*.py"))]
    return [relative]


def _matching_modules(path: str, modules):
    return [
        name for name, record in modules.items()
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in record["source_globs"])
    ]


def source_coverage_errors(root: Path, modules):
    root = Path(root)
    product_files = set()
    src_root = root / "src" / "taskweave"
    if src_root.exists():
        product_files.update(path.relative_to(root).as_posix() for path in src_root.rglob("*.py"))
    plugin_root = root / "plugins"
    if plugin_root.exists():
        for path in plugin_root.glob("*/src/**/*.py"):
            product_files.add(path.relative_to(root).as_posix())
    return sorted(path for path in product_files if not _matching_modules(path, modules))


def select_modules(names, modules, include_browser=False):
    selected = []
    reasons = OrderedDict()
    for name in names:
        if name not in modules:
            raise ValueError(f"unknown module {name!r}; use --list to see mapped modules")
        if name not in selected:
            selected.append(name)
            reasons[name] = [f"explicit module selection: {name}"]
    targets, browser_targets = [], []
    for name in selected:
        for target in modules[name]["targets"]:
            if target not in targets:
                targets.append(target)
        if include_browser:
            for target in modules[name]["browser_targets"]:
                if target not in browser_targets:
                    browser_targets.append(target)
    return {"modules": selected, "reasons": reasons, "targets": targets, "browser_targets": browser_targets}


def select_changed(paths, modules, root: Path, include_browser=False):
    root = Path(root)
    selected = []
    reasons = OrderedDict()
    unknown = []
    for path in paths:
        relative, candidate = _relative_changed(path, root)
        source_paths = _source_files_for_path(relative, candidate, root)
        matched_any = False
        for source_path in source_paths:
            matches = _matching_modules(source_path, modules)
            if matches:
                matched_any = True
                for name in matches:
                    if name not in selected:
                        selected.append(name)
                        reasons[name] = []
                    reasons[name].append(f"source matches {source_path}")
            elif _product_path(source_path):
                unknown.append(source_path)
        if not matched_any and not source_paths and _product_path(relative):
            unknown.append(relative)
    if unknown:
        paths_text = ", ".join(sorted(set(unknown)))
        raise UnmappedSourceError(f"unmapped product source path(s): {paths_text}; add source_globs and test targets to tests/module-map.json")
    if not selected:
        raise UnmappedSourceError("no mapped product modules selected; provide a src/taskweave or plugins source path")

    # Dependencies point from consumer to prerequisite; a prerequisite change
    # selects every transitive consumer.
    changed = True
    while changed:
        changed = False
        for consumer, record in modules.items():
            matched_dependencies = [dependency for dependency in record["depends_on"] if dependency in selected]
            if matched_dependencies and consumer not in selected:
                selected.append(consumer)
                reasons[consumer] = [f"depends on changed/selected module {dependency}" for dependency in matched_dependencies]
                changed = True
            elif matched_dependencies:
                for dependency in matched_dependencies:
                    reason = f"depends on changed/selected module {dependency}"
                    if reason not in reasons[consumer]:
                        reasons[consumer].append(reason)

    ordered = [name for name in modules if name in selected]
    result = select_modules(ordered, modules, include_browser)
    result["reasons"] = OrderedDict((name, reasons.get(name, result["reasons"].get(name, []))) for name in ordered)
    return result


def run_targets(targets, root: Path):
    if not targets:
        raise ValueError("selection has no unittest targets")
    return subprocess.run([sys.executable, "-m", "unittest", *targets, "-v"], cwd=root).returncode


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--map", dest="map_path", type=Path)
    parser.add_argument("--list", action="store_true", help="list mapped modules")
    parser.add_argument("--module", action="append", default=[], help="select one module; may be repeated")
    parser.add_argument("--changed", nargs="+", help="select modules affected by source paths")
    parser.add_argument("--dry-run", action="store_true", help="print selection without running tests")
    parser.add_argument("--include-browser", action="store_true", help="include explicitly mapped browser targets")
    return parser


def _print_selection(result):
    print("Selected modules:")
    for name in result["modules"]:
        print(f"  {name}")
        for reason in result["reasons"].get(name, []):
            print(f"    reason: {reason}")
    print("Unittest targets:")
    for target in result["targets"]:
        print(f"  {target}")
    print("Browser targets:")
    for target in result["browser_targets"]:
        print(f"  {target}")


def main(argv=None):
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    map_path = args.map_path or root / "tests" / "module-map.json"
    if not map_path.is_absolute():
        map_path = root / map_path
    try:
        modules = load_map(map_path, root)
        if args.list:
            for name in modules:
                print(name)
            return 0
        if bool(args.module) == bool(args.changed):
            raise ValueError("choose either --module or --changed")
        coverage = source_coverage_errors(root, modules)
        if coverage:
            raise UnmappedSourceError(
                "unmapped product Python source file(s): " + ", ".join(coverage)
                + "; add source_globs and explicit unittest targets to tests/module-map.json"
            )
        result = (
            select_modules(args.module, modules, args.include_browser)
            if args.module else
            select_changed(args.changed, modules, root, args.include_browser)
        )
        targets = list(result["targets"])
        for target in result["browser_targets"]:
            if target not in targets:
                targets.append(target)
        result["targets"] = targets
        _print_selection(result)
        if args.dry_run:
            return 0
        return run_targets(targets, root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"test selection error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
