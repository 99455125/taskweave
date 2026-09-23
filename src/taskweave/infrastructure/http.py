"""Loopback JSON API. Session token is required, including from local browsers."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from taskweave.core.validation import TaskError, dumps


def make_server(app, port=0, token=None):
    token = token or secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if (
                self.path != "/api"
                or self.headers.get("Authorization") != "Bearer " + token
            ):
                self.send_error(403)
                return
            if (
                self.headers.get("Origin")
                or self.headers.get_content_type() != "application/json"
            ):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8 * 1024 * 1024:
                    raise TaskError("REQUEST_SIZE_INVALID")
                request = json.loads(self.rfile.read(size))
                large_operations = {
                    "step.generate", "step.generate_goal", "step.diagnose",
                    "plan.generate", "plan.generation.parse",
                }
                if size > 2 * 1024 * 1024 and request.get("operation") not in large_operations:
                    raise TaskError("REQUEST_SIZE_INVALID")
                response = {
                    "ok": True,
                    "result": app.dispatch(
                        request["operation"], request.get("params", {})
                    ),
                }
                code = 200
            except TaskError as exc:
                response = {"ok": False, "error": exc.document()}
                code = 400
            except (ValueError, TypeError, KeyError):
                response = {
                    "ok": False,
                    "error": {
                        "code": "REQUEST_INVALID",
                        "message": "Invalid request fields",
                    },
                }
                code = 400
            except Exception:
                response = {
                    "ok": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Application operation failed",
                    },
                }
                code = 500
            body = dumps(response).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler), token
