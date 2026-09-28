"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from taskweave.infrastructure.http import make_server
from tests._core_fixture import CoreFixture

class HttpTaskApiTests(CoreFixture):
    def test_http_api_auth_and_task_create(self):
        server, token = make_server(self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api"
        try:
            body = json.dumps(
                {"operation": "task.create", "params": {"name": "API test"}}
            ).encode()
            with self.assertRaises(HTTPError):
                urlopen(
                    Request(
                        url, data=body, headers={"Content-Type": "application/json"}
                    )
                )
            with urlopen(
                Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + token,
                    },
                )
            ) as response:
                result = json.load(response)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["name"], "API test")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
