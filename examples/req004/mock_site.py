"""Local mock business site: an order, guarded submission, and download."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

HTML = """<!doctype html><html><head><title>TaskWeave Order</title></head><body>
<h1>Local order</h1><input id="name" aria-label="Order name"><button id="submit">Submit</button>
<div id="status">draft</div><div id="order-id"></div><div id="count">0</div>
<a id="download" href="/download">Download</a>
<script>
async function refresh(){let r=await fetch('/state');let s=await r.json();document.querySelector('#status').textContent=s.status;document.querySelector('#order-id').textContent=s.order_id;document.querySelector('#count').textContent=s.count;document.querySelector('#status').setAttribute('data-loaded','true');}
document.querySelector('#submit').onclick=async()=>{await fetch('/submit',{method:'POST'});await refresh();};refresh();
</script></body></html>"""


SEARCH_HTML = """<!doctype html><html><head><title>Search home</title></head><body>
<input id="old-query" style="display:none"><input id="old-submit" type="submit" value="Search" style="display:none">
<textarea id="search-editor" aria-label="Search query"></textarea><button id="search-submit">Search</button>
<div id="results"></div><iframe id="embedded" srcdoc='<input aria-label="Frame query">'></iframe>
<script>document.querySelector('#search-submit').onclick=()=>{const q=document.querySelector('#search-editor').value;setTimeout(()=>{document.title=q+' - Results';document.querySelector('#results').textContent='Results for '+q;history.pushState({},'', '/search-results?query='+encodeURIComponent(q));},150)};</script>
</body></html>"""


def make_site():
    state = {"status": "draft", "order_id": "", "count": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/download":
                body = b"order_id,amount\nORDER-001,200\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="order.csv"'
                )
            elif self.path == "/state":
                with lock:
                    body = json.dumps(state).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            elif self.path.startswith("/search-demo"):
                body = SEARCH_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
            else:
                body = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/submit":
                self.send_error(404)
                return
            with lock:
                state.update(
                    status="submitted", order_id="ORDER-001", count=state["count"] + 1
                )
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return server, state
