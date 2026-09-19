"""Real browser walkthrough via application services; no model or UI required."""

import argparse
import json
import threading
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid
from mock_site import make_site


def run(app, url, headed=False):
    app.dispatch("plugin.configure", {"plugin_id": "playwright", "enabled": True})
    environment = app.repo.save_environment(
        "Local browser", {"browser": {"headless": not headed, "timeout_ms": 3000}}
    )["environment_id"]
    task = app.repo.create_task("REQ-004 browser plugin")
    definitions = [
        (
            "Open and read",
            """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"]})
    title = await ctx.call("playwright.page_title", {})
    assert title["title"] == "TaskWeave Order"
    return ctx.result(data=title)
""",
            {"url": {"literal": url}},
            ["playwright.page_open", "playwright.page_title"],
        ),
        (
            "Guarded submit",
            """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"]})
    await ctx.call("playwright.page_wait", {"selector": "#status[data-loaded=true]"})
    status = await ctx.call("playwright.page_text", {"selector": "#status[data-loaded=true]"})
    if status["text"] != "submitted":
        await ctx.call("playwright.page_fill", {"selector": "#name", "value": "Demo"})
        await ctx.call("playwright.page_click", {"selector": "#submit"})
    await ctx.call("playwright.page_wait", {"selector": "#order-id:not(:empty)"})
    await ctx.call("playwright.page_assert_text", {"selector": "#status", "text": "submitted"})
    order = await ctx.call("playwright.page_text", {"selector": "#order-id"})
    assert order["text"]
    return ctx.result(data={"order_id": order["text"]})
""",
            {"url": {"literal": url}},
            [
                "playwright.page_open",
                "playwright.page_wait",
                "playwright.page_text",
                "playwright.page_fill",
                "playwright.page_click",
                "playwright.page_assert_text",
            ],
        ),
    ]
    steps = []
    for name, source, bindings, caps in definitions:
        step = app.repo.save_step(
            task["task_id"],
            {
                "name": name,
                "step_content": source,
                "bindings": bindings,
                "capabilities": caps,
            },
        )
        trial = app.trial_step(step["step_id"], {"url": url}, uid(), environment)
        done = app.coordinator.wait(trial["run_id"])
        assert done["status"] == "SUCCEEDED", done
        app.confirm_step(
            step["step_id"], done["attempts"][0]["attempt_id"], step["content_hash"]
        )
        steps.append(step)
    source = """async def run(ctx, inputs):
    assert inputs["order_id"] == "ORDER-001"
    await ctx.call("playwright.page_open", {"url": inputs["url"]})
    capture = await ctx.call("playwright.page_screenshot", {})
    download = await ctx.call("playwright.page_download", {"selector": "#download"})
    return ctx.result(data={"received_order_id": inputs["order_id"]}, outputs=[ctx.output("playwright.image", "capture", capture), ctx.output("playwright.download", "download", download)])
"""
    step = app.repo.save_step(
        task["task_id"],
        {
            "name": "Use persisted order and save files",
            "step_content": source,
            "bindings": {
                "url": {"literal": url},
                "order_id": {
                    "ref": {
                        "source": "step",
                        "step_id": steps[1]["step_id"],
                        "pointer": "/order_id",
                    }
                },
            },
            "capabilities": [
                "playwright.page_open",
                "playwright.page_screenshot",
                "playwright.page_download",
                "playwright.image",
                "playwright.download",
            ],
        },
    )
    trial = app.trial_step(
        step["step_id"], {"url": url, "order_id": "ORDER-001"}, uid(), environment
    )
    done = app.coordinator.wait(trial["run_id"])
    assert done["status"] == "SUCCEEDED", done
    app.confirm_step(
        step["step_id"], done["attempts"][0]["attempt_id"], step["content_hash"]
    )
    run = app.create_run(task["task_id"], environment_id=environment)
    app.coordinator.start(run["run_id"], uid(), mode="NEXT")
    paused = app.coordinator.wait(run["run_id"])
    assert paused["status"] == "PAUSED", paused
    app.coordinator.start(run["run_id"], uid())
    done = app.coordinator.wait(run["run_id"])
    assert done["status"] == "SUCCEEDED", done
    return {
        "status": done["status"],
        "run_id": run["run_id"],
        "output": app.repo.read_output(run["run_id"], step["step_id"]),
        "files": [
            app.repo.read_result(r["result_id"], app.registry)
            for r in done["results"]
            if r["kind"] == "file"
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=".runtime/req004-demo")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    server, state = make_site()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with Application(args.home) as app:
            result = run(app, f"http://127.0.0.1:{server.server_port}", args.headed)
            assert state["count"] == 1, state
            print(
                json.dumps(
                    {**result, "business_submit_count": state["count"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


if __name__ == "__main__":
    main()
