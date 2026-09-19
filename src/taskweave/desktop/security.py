"""Authenticate both HTTP and Socket.IO with a per-process loopback cookie."""

from http.cookies import SimpleCookie
import secrets
from urllib.parse import parse_qs
from starlette.responses import PlainTextResponse, RedirectResponse


class LocalAccess:
    def __init__(self, app, token, port):
        self.app, self.token, self.port = app, token, port
        self.cookie_name = "taskweave_" + str(port)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        host_ok = headers.get("host") in hosts
        origin = headers.get("origin")
        origin_ok = not origin or origin in {"http://" + h for h in hosts}
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
            value = cookie.get(self.cookie_name)
            authorized = value is not None and secrets.compare_digest(
                value.value, self.token
            )
        except Exception:
            authorized = False
        query = parse_qs(scope.get("query_string", b"").decode())
        access = query.get("access", [""])[0]
        if (
            host_ok
            and origin_ok
            and scope["type"] == "http"
            and scope["path"] in {"/", "/logs"}
            and secrets.compare_digest(access, self.token)
        ):
            response = RedirectResponse(scope["path"], status_code=303)
            response.set_cookie(
                self.cookie_name, self.token, httponly=True, samesite="strict"
            )
            return await response(scope, receive, send)
        if not host_ok or not origin_ok or not authorized:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await PlainTextResponse(
                    "请通过 TaskWeave 启动入口访问。", status_code=403
                )(scope, receive, send)
            return
        await self.app(scope, receive, send)
