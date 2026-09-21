"""Start one loopback server and an optional native window; safe under spawn."""

import asyncio
import json
import logging
import multiprocessing
import os
from pathlib import Path
import secrets
import socket
import sys


def select_local_port():
    """Ask the OS for a free IPv4 loopback port, matching the server host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def launch(home=None, port=None, browser=False):
    multiprocessing.freeze_support()
    if getattr(sys, "frozen", False):
        bundle_root = Path(sys.executable).resolve().parent
        bundled_browsers = bundle_root / "browsers"
        if bundled_browsers.is_dir():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled_browsers))
    try:
        from nicegui import app, ui

        if not browser:
            import webview  # noqa: F401
    except ImportError as exc:
        from taskweave.core.validation import TaskError

        raise TaskError(
            "GUI_DEPENDENCY_MISSING",
            "使用 uv run --extra gui taskweave workbench 安装并运行界面",
        ) from exc
    from taskweave.application.service import Application
    from taskweave.desktop.controller import DesktopController
    from taskweave.desktop.security import LocalAccess
    from taskweave.desktop.workbench import Workbench
    from taskweave.infrastructure.model import HttpModel, configured_model
    from taskweave.infrastructure.storage import default_home

    home = Path(home or default_home()).resolve()
    if home is not None:
        from taskweave.infrastructure.storage import workspace_location_file
        location = workspace_location_file()
        if location.exists():
            try:
                location_data = json.loads(location.read_text(encoding='utf-8'))
                old = Path(location_data.get('remove_after_restart', '')).resolve()
                if old != home and old.exists():
                    import shutil
                    shutil.rmtree(old)
                location_data.pop('remove_after_restart', None)
                location.write_text(json.dumps(location_data, ensure_ascii=False), encoding='utf-8')
            except (OSError, ValueError):
                logging.getLogger(__name__).warning('旧工作空间将在下次启动继续清理')
    port = port if port is not None else select_local_port()
    token = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{port}/?access={token}"
    holder = {}
    from taskweave.desktop.server_logs import ServerLogs, log_window, render_logs
    logs = ServerLogs(home)
    logs.protect(token)
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(logs)
    viewer = None

    async def open_logs():
        nonlocal viewer
        if browser:
            ui.navigate.to('/logs', new_tab=True)
        elif viewer is None or not viewer.is_alive():
            viewer = multiprocessing.get_context('spawn').Process(
                target=log_window, args=(f'http://127.0.0.1:{port}/logs?access={token}',),
            )
            viewer.start()

    async def startup():
        model = configured_model()
        settings_path = home / "model.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            if settings.get("url") and settings.get("model"):
                model = HttpModel(
                    settings["url"],
                    settings["model"],
                    settings.get("api_key") or os.getenv(settings.get("key_env", "")),
                )
        holder["application"] = await asyncio.to_thread(Application, home, model)
        holder["controller"] = DesktopController(holder["application"])
        holder["controller"].native = not browser
        holder["controller"].open_logs = open_logs
        holder["controller"].server_logs = logs
        logs.protect(getattr(model, 'api_key', None))
        logging.getLogger(__name__).info('服务启动，监听 127.0.0.1:%s', port)

    async def shutdown():
        if viewer and viewer.is_alive():
            viewer.terminate()
            await asyncio.to_thread(viewer.join, 5)
        if holder.get("application"):
            await asyncio.to_thread(holder.pop("application").close)
        root_logger.removeHandler(logs)
        root_logger.setLevel(previous_level)
        logs.close()

    app.on_startup(startup)
    app.on_shutdown(shutdown)
    app.add_middleware(LocalAccess, token=token, port=port)

    @ui.page('/logs')
    async def log_page():
        render_logs(logs, holder["controller"].open_path)

    @ui.page("/")
    async def index():
        workbench = Workbench(holder["controller"])
        await workbench.paint()
        if not browser:

            async def native_ready():
                try:
                    size = await asyncio.wait_for(app.native.main_window.get_size(), 10)
                    print(
                        json.dumps(
                            {
                                "native_window_ready": True,
                                "size": size,
                                "platform": sys.platform,
                            }
                        ),
                        flush=True,
                    )
                except (TimeoutError, RuntimeError):
                    print(
                        json.dumps(
                            {"native_window_ready": False, "platform": sys.platform}
                        ),
                        flush=True,
                    )

            ui.context.client.on_connect(native_ready)

    if not browser:
        app.native.window_args.update(url=url, min_size=(860, 600))
        if sys.platform == "win32":
            app.native.start_args["gui"] = "edgechromium"
            candidates = [
                Path(sys.executable).parent / "webview2",
                Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
                / "webview2",
            ]
            fixed = next((path for path in candidates if path.is_dir()), None)
            if fixed:
                os.environ["WEBVIEW2_RUNTIME_PATH"] = str(fixed)
                webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(fixed)
    print(
        json.dumps({"url": url, "home": str(home), "native": not browser}), flush=True
    )
    ui.run(
        host="127.0.0.1",
        port=port,
        native=not browser,
        window_size=None if browser else (1280, 850),
        title="TaskWeave · 任务织流",
        show=False,
        reload=False,
        language="zh-CN",
        show_welcome_message=False,
        fastapi_docs=False,
    )
