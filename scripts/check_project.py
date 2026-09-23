"""Dependency-free structural checks; never imports the legacy application."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    errors = []
    required = (
        "pyproject.toml", "README.md", "AGENTS.md", "AI_GUIDE.md", "CLAUDE.md",
        "TASK_TEMPLATE.md", "src/taskweave/core", "src/taskweave/plugins",
        "src/taskweave/application", "src/taskweave/infrastructure",
        "plugins/playwright", "plugins/ocr", "plugins/tidb", "apps", "config", "examples", "tests",
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
        if "core" not in path.relative_to(ROOT / "src" / "taskweave").parts:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in forbidden:
                    errors.append(f"Unexpected runtime dependency in {path}: {name}")
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
    print(f"PASS: layout, source syntax, dependency boundaries, {len(docs)} Markdown files, CLI version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
