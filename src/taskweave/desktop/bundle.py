"""Packaged desktop resources and first-launch plugin configuration."""

import json
import os
from pathlib import Path
import sys


BUNDLED_PLUGINS = (
    'playwright', 'ocr', 'tidb', 'utility', 'file', 'process', 'ssh',
    'baota_dashboard', 'wordpress', 'uniapp', 'wechat_dev', 'pdf', 'dataset', 'excel', 'nacos',
)


def bundled_browser_path() -> Path | None:
    if not getattr(sys, 'frozen', False):
        return None
    roots = [Path(sys.executable).resolve().parent]
    if sys.platform == 'darwin':
        roots.insert(0, Path(sys.executable).resolve().parent.parent / 'Resources')
    if hasattr(sys, '_MEIPASS'):
        roots.insert(0, Path(sys._MEIPASS))
    return next((root / 'browsers' for root in roots if (root / 'browsers').is_dir()), None)


def initialize_bundled_plugins(home: Path, plugin_ids: tuple[str, ...]) -> bool:
    from taskweave.infrastructure.locking import InstanceLock
    from taskweave.plugins.manager import PluginManager

    manager = PluginManager(home)
    if manager.path.exists() or manager.path.is_symlink():
        manager.enabled()  # Report malformed existing configuration without replacing it.
        return False
    lock = InstanceLock(home / 'coordinator.lock')
    try:
        manager.registry(list(plugin_ids))  # Missing dependencies cannot produce a partial config.
        try:
            fd = os.open(manager.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            manager.enabled()
            return False
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'format': 1, 'enabled': list(plugin_ids)}, stream)
        return True
    finally:
        lock.close()


def record_startup_failure(home: Path, exc: Exception) -> Path | None:
    """Record public diagnostics even when GUI/server logging never initialized."""
    import logging
    from taskweave.core.validation import TaskError
    from taskweave.desktop.server_logs import ServerLogs

    code = exc.code if isinstance(exc, TaskError) else type(exc).__name__
    try:
        logs = ServerLogs(home)
        try:
            record = logging.LogRecord('taskweave.startup', logging.ERROR, __file__, 0,
                                       'startup failed [%s]', (code,), None)
            logs.handle(record)
            return logs.path
        finally:
            logs.close()
    except OSError:
        return None


def main(argv=None):
    """macOS app entry after PyInstaller's child-process dispatch."""
    import argparse
    from taskweave.infrastructure.sqlite_storage import default_home

    parser = argparse.ArgumentParser(description='TaskWeave macOS')
    parser.add_argument('--home')
    parser.add_argument('--diagnose', action='store_true')
    args = parser.parse_args(argv)
    browsers = bundled_browser_path()
    if browsers is not None:
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(browsers)
    if args.diagnose:
        from importlib.metadata import entry_points
        from taskweave.plugins.manager import PluginManager
        registry = PluginManager(Path('.')).registry(list(BUNDLED_PLUGINS))
        print(json.dumps({
            'frozen': bool(getattr(sys, 'frozen', False)),
            'plugins': sorted(registry.versions),
            'entry_points': sorted(e.name for e in entry_points(group='taskweave.plugins')),
            'browser_bundled': browsers is not None,
        }))
        return 0
    home = Path(args.home or default_home()).expanduser().resolve()
    try:
        initialize_bundled_plugins(home, BUNDLED_PLUGINS)
        from taskweave.desktop.launcher import launch
        launch(home=home)
    except Exception as exc:
        # A native alert remains visible even when Finder has no terminal attached.
        from taskweave.core.validation import TaskError
        code = exc.code if isinstance(exc, TaskError) else type(exc).__name__
        log = record_startup_failure(home, exc)
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_('TaskWeave 无法启动')
        detail = f'日志：{log}' if log else '启动日志无法写入，请检查工作空间目录权限。'
        alert.setInformativeText_(f'错误：{code}\n工作空间：{home}\n{detail}\n已有数据保留。')
        alert.runModal()
        return 1
    return 0
