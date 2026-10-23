"""Export packaged guidance without overwriting an existing personal skill."""
from importlib.resources import files
from pathlib import Path
import sys
from taskweave.core.validation import TaskError


def skill_files():
    root = files('taskweave.integration').joinpath('skill_assets')
    def visit(folder, prefix=''):
        for item in folder.iterdir():
            name = prefix + item.name
            if item.is_dir():
                yield from visit(item, name + '/')
            else:
                yield name, item.read_bytes()
    return dict(visit(root))


def install_skill(destination):
    destination = Path(destination).expanduser().absolute()
    payloads = skill_files()
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and not destination.is_symlink() and all(
                (destination / name).is_file() and not (destination / name).is_symlink()
                and (destination / name).read_bytes() == data for name, data in payloads.items()):
            return {'status': 'unchanged', 'path': str(destination)}
        raise TaskError('SKILL_DESTINATION_CONFLICT', '目标目录已有不同内容，请选择新目录或先人工合并')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        # mkdir claims the destination exclusively; an existing directory is never replaced.
        destination.mkdir()
        for name in payloads:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(payloads[name])
    except FileExistsError as exc:
        raise TaskError('SKILL_DESTINATION_CONFLICT') from exc
    return {'status': 'installed', 'path': str(destination)}


def connection_config(home):
    if getattr(sys, 'frozen', False):
        # The bundled GUI executable has a different entrypoint. Use an installed CLI bridge.
        command, prefix = 'taskweave', []
    else:
        command, prefix = sys.executable, ['-m', 'taskweave']
    return {'mcpServers': {'taskweave': {'command': command, 'args': prefix + ['--home', str(Path(home).resolve()), 'mcp']}}}
