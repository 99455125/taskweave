"""End markers follow the entire scrollable flow at every supported zoom."""
import socket
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen


class FlowCanvasLayoutTests(unittest.TestCase):
    def test_end_follows_last_node_in_long_and_nested_flows(self):
        from playwright.sync_api import sync_playwright
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='taskweave-flow-layout-') as temporary:
            log_path = Path(temporary) / 'server.log'
            with log_path.open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'tests._flow_canvas_fixture', str(port)], stdout=log, stderr=log)
                try:
                    url = f'http://127.0.0.1:{port}/'
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            with urlopen(url, timeout=1):
                                break
                        except OSError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                self.fail(log_path.read_text())
                            time.sleep(.1)
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        try:
                            page = browser.new_page()
                            page.goto(url)
                            page.locator('.tw-flow-node').first.wait_for()
                            page.wait_for_function("getComputedStyle(document.querySelector('.tw-flow-node')).width === '220px'")
                            for width in (1000, 600):
                                page.set_viewport_size({'width': width, 'height': 900})
                                for zoom in (.75, 1, 1.25):
                                    for kind in ('linear', 'nested', 'loop', 'empty-nested'):
                                        with self.subTest(width=width, zoom=zoom, kind=kind):
                                            canvas = page.locator(f'[data-layout="{kind}"] .tw-flow-canvas')
                                            metrics = canvas.evaluate('''(canvas, zoom) => {
                                                const root = canvas.querySelector('.tw-flow-root');
                                                root.style.zoom = zoom;
                                                canvas.scrollLeft = canvas.scrollWidth;
                                                const end = root.lastElementChild.getBoundingClientRect();
                                                const nodes = [...root.querySelectorAll('.tw-flow-node')].map(n => n.getBoundingClientRect());
                                                const body = root.querySelector(':scope > .tw-flow-sequence').getBoundingClientRect();
                                                return {endLeft:end.left,endRight:end.right,bodyRight:body.right,
                                                    nodeRight:Math.max(...nodes.map(n=>n.right)),
                                                    canvasRight:canvas.getBoundingClientRect().right};
                                            }''', zoom)
                                            page.wait_for_timeout(60)
                                            routes = canvas.evaluate('''canvas => [...canvas.querySelectorAll('.tw-flow-branches')].map(group => {
                                                const svg = group.querySelector(':scope > svg');
                                                const rows = [...group.querySelectorAll(':scope > .tw-flow-branch')];
                                                return {paths: svg ? svg.querySelectorAll('path').length : 0, rows: rows.length};
                                            })''')
                                            for route in routes:
                                                self.assertEqual(route['paths'], route['rows'] * 2, route)
                                            self.assertGreaterEqual(metrics['endLeft'], metrics['nodeRight'] + 8 * zoom, metrics)
                                            self.assertGreaterEqual(metrics['bodyRight'] + 1, metrics['nodeRight'], metrics)
                                            self.assertGreaterEqual(metrics['endLeft'], metrics['bodyRight'], metrics)
                                            self.assertLessEqual(metrics['endRight'], metrics['canvasRight'] + 1, metrics)
                        finally:
                            browser.close()
                    if sys.platform == 'darwin':
                        native = subprocess.run([sys.executable, '-m', 'tests._flow_canvas_webkit', url],
                                                capture_output=True, text=True, timeout=35)
                        self.assertEqual(native.returncode, 0, native.stderr)
                        for metrics in json.loads(native.stdout):
                            with self.subTest(engine='WKWebView', **{key: metrics[key] for key in ('width', 'zoom', 'kind')}):
                                self.assertGreaterEqual(metrics['endLeft'], metrics['nodeRight'] + 8 * metrics['zoom'], metrics)
                                self.assertGreaterEqual(metrics['bodyRight'] + 1, metrics['nodeRight'], metrics)
                                self.assertLessEqual(metrics['endRight'], metrics['canvasRight'] + 1, metrics)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
