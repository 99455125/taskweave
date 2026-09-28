"""Stateless plan row decoding and revision validation helpers."""

import json
from taskweave.core.validation import TaskError


def decode_plan(plan):
    plan = dict(plan)
    plan["plugin_ids"] = json.loads(plan.pop("plugin_ids_json"))
    return plan


def expect_plan_revision(db, plan_id, revision):
    row = db.execute("SELECT revision FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
    if row is None:
        raise TaskError("PLAN_NOT_FOUND", plan_id)
    if row[0] != revision:
        raise TaskError("EDIT_CONFLICT", f"计划已更新：当前版本 {row[0]}，请求版本 {revision}")
