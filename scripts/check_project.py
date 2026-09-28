"""Dependency-free structural checks; never imports the legacy application."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _attribute_chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def runtime_boundary_violations(tree):
    return [
        f"line {node.lineno}: {'.'.join(_attribute_chain(node.func))}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"query", "execute", "transaction"}
    ]


def application_boundary_violations(tree):
    violations = []
    sql_start = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP)\b", re.I)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        chain = _attribute_chain(node.func)
        is_sql_execute = False
        if node.func.attr == "execute" and node.args:
            statement = node.args[0]
            if isinstance(statement, ast.Constant) and isinstance(statement.value, str):
                is_sql_execute = bool(sql_start.match(statement.value))
            elif isinstance(statement, ast.JoinedStr):
                first = next((part.value for part in statement.values if isinstance(part, ast.Constant) and isinstance(part.value, str)), "")
                is_sql_execute = bool(sql_start.match(first))
        repository_write = node.func.attr in {"execute", "transaction"} and any(
            part in {"repo", "repository", "repositories", "runs", "tasks", "steps", "results"}
            for part in chain[:-1]
        )
        if node.func.attr == "query" or is_sql_execute or repository_write:
            violations.append(f"line {node.lineno}: {'.'.join(chain)}")
    return violations


def controller_boundary_violations(tree):
    violations = []
    repository_names = {"repo", "repository", "repositories", "store", "query", "execute", "transaction"}
    use_case_names = {"tasks", "steps", "environments", "runs", "contexts", "planning", "operations"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        chain = _attribute_chain(node.func)
        if "application" not in chain:
            continue
        app_index = chain.index("application")
        intermediate = chain[app_index + 1:-1]
        if any(part in repository_names for part in intermediate) or (
            intermediate and intermediate[0] in use_case_names and len(intermediate) > 1
        ):
            violations.append(f"line {node.lineno}: {'.'.join(chain)}")
    return violations


def main():
    errors = []
    required = (
        "pyproject.toml", "README.md", "AGENTS.md", "AI_GUIDE.md", "CLAUDE.md",
        "TASK_TEMPLATE.md", "src/taskweave/core", "src/taskweave/plugins",
        "src/taskweave/application", "src/taskweave/infrastructure",
        "plugins/playwright", "plugins/ocr", "plugins/tidb", "plugins/utility", "apps", "config", "examples", "tests",
        "docs/architecture.md", "docs/progress.md", "docs/project-plan.md",
        "docs/ai-operating-model.md", "docs/engineering-playbook.md",
        "docs/testing.md", "docs/deployment.md", "docs/migration.md",
        "docs/requirements/REQ-001-requirement-pool/validation.md",
    )
    for name in required:
        if not (ROOT / name).exists():
            errors.append(f"Missing: {name}")
    forbidden = {"app", "db_server", "deepseek", "tools", "legacy", "pandas",
                 "openpyxl", "playwright", "openai", "sqlalchemy", "flask"}
    for path in (ROOT / "src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(str(exc))
            continue
        is_core = "core" in path.relative_to(ROOT / "src" / "taskweave").parts
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if is_core:
                for name in names:
                    if name.split(".")[0] in forbidden:
                        errors.append(f"Unexpected runtime dependency in {path}: {name}")
        relative = path.relative_to(ROOT / "src" / "taskweave")
        if relative.parts and relative.parts[0] == "application":
            for violation in application_boundary_violations(tree):
                errors.append(f"Application persistence bypass must use a repository: {path}:{violation}")
        runtime_path = ROOT / "src/taskweave/infrastructure/runtime.py"
        if path == runtime_path:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for violation in runtime_boundary_violations(tree):
                errors.append(f"Coordinator persistence SQL must use RunRepository: {path}:{violation}")
        controller_path = ROOT / "src/taskweave/desktop/controller.py"
        if path == controller_path:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for violation in controller_boundary_violations(tree):
                errors.append(f"DesktopController must use application queries: {path}:{violation}")
    docs = list(ROOT.glob("*.md"))
    for folder in ("docs", "src", "plugins", "apps", "config", "examples", "scripts", "tests"):
        docs.extend((ROOT / folder).rglob("*.md"))
    for path in docs:
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            if not (path.parent / target).exists():
                errors.append(f"Broken link in {path.relative_to(ROOT)}: {target}")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-m", "taskweave", "--version"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode or result.stdout.strip() != "TaskWeave 0.1.0":
        errors.append(f"Version smoke check failed: {result.stdout}{result.stderr}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS: layout, source syntax, application/runtime/desktop dependency boundaries, {len(docs)} Markdown files, CLI version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
