"""Runnable CLI and loopback API entry point."""

import argparse
import json
import multiprocessing
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from taskweave import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description="TaskWeave — 本地任务与步骤自动化")
    parser.add_argument(
        "--version", action="version", version=f"TaskWeave {__version__}"
    )
    parser.add_argument(
        "--home", help="Local data directory; otherwise TASKWEAVE_HOME/platform default"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("demo", help="Run and validate the five-step SQLite example")
    workbench = sub.add_parser(
        "workbench", help="Start the cross-platform native workbench"
    )
    workbench.add_argument("--port", type=int)
    workbench.add_argument(
        "--browser",
        action="store_true",
        help="Developer browser inspection instead of a native window",
    )
    serve = sub.add_parser("serve", help="Start local application API (no UI)")
    serve.add_argument("--port", type=int, default=8765)
    request = sub.add_parser(
        "request", help="Send a JSON request file to the running application"
    )
    request.add_argument("file", help="JSON file, or - for stdin")
    request.add_argument("--url", default="http://127.0.0.1:8765/api")
    plugins = sub.add_parser(
        "plugins", help="List installed plugins or configure explicit enablement"
    )
    plugins.add_argument("action", choices=["list", "enable", "disable"])
    plugins.add_argument("plugin_id", nargs="?")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    from taskweave.core.validation import TaskError

    try:
        if args.command == "workbench":
            from taskweave.desktop.launcher import launch

            try:
                launch(args.home, args.port, args.browser)
            except KeyboardInterrupt:
                pass
            return 0
        if args.command == "request":
            from urllib.parse import urlparse

            parsed = urlparse(args.url)
            if parsed.scheme != "http" or parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise TaskError(
                    "API_URL_INVALID", "The application API is loopback only"
                )
            token = os.getenv("TASKWEAVE_API_TOKEN")
            if not token:
                raise TaskError(
                    "API_TOKEN_MISSING", "Set TASKWEAVE_API_TOKEN to the server token"
                )
            body = (
                sys.stdin.read()
                if args.file == "-"
                else Path(args.file).read_text(encoding="utf-8")
            )
            try:
                with urlopen(
                    Request(
                        args.url,
                        data=body.encode(),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": "Bearer " + token,
                        },
                    ),
                    timeout=190,
                ) as response:
                    result = json.load(response)
            except HTTPError as exc:
                result = json.load(exc)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        from taskweave.application.service import Application
        from taskweave.infrastructure.model import configured_model

        with Application(args.home, model=configured_model()) as app:
            if args.command == "plugins":
                if args.action == "list":
                    result = app.installed_plugins()
                else:
                    if not args.plugin_id:
                        raise TaskError("PLUGIN_ID_REQUIRED")
                    result = app.configure_plugin(
                        args.plugin_id, args.action == "enable"
                    )
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.command == "demo":
                from taskweave.application.demo import run_demo

                print(json.dumps(run_demo(app), ensure_ascii=False, indent=2))
            else:
                from taskweave.infrastructure.http import make_server

                server, token = make_server(
                    app, args.port, os.getenv("TASKWEAVE_API_TOKEN")
                )
                print(
                    json.dumps(
                        {
                            "url": f"http://127.0.0.1:{server.server_port}/api",
                            "token": token,
                            "home": str(app.home),
                        }
                    ),
                    flush=True,
                )
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.server_close()
        return 0
    except TaskError as exc:
        print(
            json.dumps({"ok": False, "error": exc.document()}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
