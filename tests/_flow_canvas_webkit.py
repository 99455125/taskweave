"""Measure a local canvas in macOS's native WKWebView without showing a window."""
import json
import sys
import time

from AppKit import NSApplication, NSMakeRect, NSWindow
from Foundation import NSDate, NSRunLoop, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration


def evaluate(view, script):
    pending = []
    view.evaluateJavaScript_completionHandler_(script, lambda result, error: pending.append((result, error)))
    deadline = time.monotonic() + 10
    while not pending and time.monotonic() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.02))
    if not pending:
        raise RuntimeError('WKWebView evaluation timed out')
    result, error = pending[0]
    if error:
        raise RuntimeError(str(error))
    return result


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(2)
    frame = NSMakeRect(0, 0, 1000, 900)
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(frame, 0, 2, False)
    view = WKWebView.alloc().initWithFrame_configuration_(frame, WKWebViewConfiguration.new())
    window.setContentView_(view)
    view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(sys.argv[1])))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        ready = evaluate(view, "!!document.querySelector('.tw-flow-node') && getComputedStyle(document.querySelector('.tw-flow-node')).width === '220px'")
        if ready:
            break
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.1))
    else:
        raise RuntimeError('Local canvas did not become ready')
    rows = []
    for width in (1000, 600):
        window.setContentSize_((width, 900))
        view.setFrame_(NSMakeRect(0, 0, width, 900))
        for zoom in (.75, 1, 1.25):
            rows.extend(json.loads(evaluate(view, '''JSON.stringify([...document.querySelectorAll('[data-layout]')].map(panel => {
                const canvas=panel.querySelector('.tw-flow-canvas'), root=canvas.querySelector('.tw-flow-root');
                root.style.zoom=ZOOM;
                canvas.scrollLeft=canvas.scrollWidth;
                const end=root.lastElementChild.getBoundingClientRect();
                const nodes=[...root.querySelectorAll('.tw-flow-node')].map(n=>n.getBoundingClientRect());
                return {kind:panel.dataset.layout,width:WIDTH,zoom:ZOOM,endLeft:end.left,endRight:end.right,
                    bodyRight:root.querySelector(':scope > .tw-flow-sequence').getBoundingClientRect().right,
                    nodeRight:Math.max(...nodes.map(n=>n.right)),canvasRight:canvas.getBoundingClientRect().right};
            }))'''.replace('ZOOM', str(zoom)).replace('WIDTH', str(width)))))
    print(json.dumps(rows))
    view.stopLoading()
    window.close()


if __name__ == '__main__':
    main()
