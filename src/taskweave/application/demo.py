"""Executable acceptance example: step five reads step one from SQLite."""

from taskweave.infrastructure.storage import uid
from taskweave.core.validation import TaskError


def run_demo(app):
    task = app.repo.create_task("REQ-003 five-step database demo")
    task_id = task["task_id"]
    steps = []
    for i in range(5):
        data = {"order_id": "ORD-1001", "amount": 200} if i == 0 else {"step": i + 1}
        source = (
            "async def run(ctx, inputs):\n    return ctx.result(data="
            + repr(data)
            + ")\n"
        )
        bindings = {}
        sample = {}
        if i == 4:
            source = 'async def run(ctx, inputs):\n    assert inputs["order_id"] == "ORD-1001"\n    return ctx.result(data={"received_order_id": inputs["order_id"]})\n'
            bindings = {
                "order_id": {
                    "ref": {
                        "source": "step",
                        "step_id": steps[0]["step_id"],
                        "pointer": "/order_id",
                    }
                }
            }
            sample = {"order_id": "ORD-1001"}
        step = app.repo.save_step(
            task_id,
            {"name": f"Step {i + 1}", "step_content": source, "bindings": bindings},
        )
        trial = app.trial_step(step["step_id"], sample, uid())
        done = app.coordinator.wait(trial["run_id"])
        if done["status"] != "SUCCEEDED":
            raise TaskError("DEMO_TRIAL_FAILED", str(done))
        step = app.confirm_step(
            step["step_id"], done["attempts"][0]["attempt_id"], step["content_hash"]
        )
        steps.append(step)
    run = app.create_run(task_id)
    app.coordinator.start(run["run_id"], uid(), mode="NEXT")
    paused = app.coordinator.wait(run["run_id"])
    if paused["status"] != "PAUSED":
        raise TaskError("DEMO_PAUSE_FAILED")
    # The producer worker is deliberately replaced; data is read from the task DB.
    app.coordinator._stop_worker()
    app.coordinator.start(run["run_id"], uid())
    done = app.coordinator.wait(run["run_id"])
    if done["status"] != "SUCCEEDED":
        raise TaskError("DEMO_RUN_FAILED", str(done))
    output = app.repo.read_output(run["run_id"], steps[4]["step_id"])
    return {
        "status": done["status"],
        "task_id": task_id,
        "run_id": run["run_id"],
        "step_1_id": steps[0]["step_id"],
        "step_5_id": steps[4]["step_id"],
        "step_5_output": output,
        "control_db": str(app.repo.path),
        "task_db": str(app.repo.task_path(task_id)),
    }
