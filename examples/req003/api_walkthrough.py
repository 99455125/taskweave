"""Run against `taskweave serve`; uses only the Python standard library."""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4


def call(operation, **params):
    token = os.environ["TASKWEAVE_API_TOKEN"]
    request = Request(
        "http://127.0.0.1:8765/api",
        data=json.dumps({"operation": operation, "params": params}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            reply = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(exc.read().decode()) from exc
    return reply["result"]


def main():
    task = call("task.create", name="HTTP 接口验收")
    step = call(
        "step.save",
        task_id=task["task_id"],
        document={
            "name": "返回订单号",
            "step_content": 'async def run(ctx, inputs):\n    return ctx.result(data={"order_id": "API-1001"})\n',
        },
    )
    trial = call(
        "step.trial", step_id=step["step_id"], inputs={}, command_id=str(uuid4())
    )
    done = call("run.wait", run_id=trial["run_id"])
    assert done["status"] == "SUCCEEDED", done
    call(
        "step.confirm",
        step_id=step["step_id"],
        attempt_id=done["attempts"][0]["attempt_id"],
        expected_hash=step["content_hash"],
    )
    run = call("run.create", task_id=task["task_id"])
    call("run.start", run_id=run["run_id"], command_id=str(uuid4()))
    done = call("run.wait", run_id=run["run_id"])
    assert done["status"] == "SUCCEEDED", done
    output = call("run.output", run_id=run["run_id"], step_id=step["step_id"])
    print(
        json.dumps(
            {"status": done["status"], "output": output, "run_id": run["run_id"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
