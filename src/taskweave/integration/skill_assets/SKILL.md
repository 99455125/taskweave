---
name: taskweave
description: Author, validate and execute reusable local TaskWeave tasks and task sequences through MCP, and open persisted evidence for human acceptance. Use when the user asks to automate work with TaskWeave or run an existing TaskWeave task.
---

# TaskWeave

Use TaskWeave's installed plugins and deterministic executor to turn a goal into a reusable task. Use the connected `taskweave_*` tools. Start the same workspace's workbench (or `serve` for headless work) before connecting; a missing owner requires starting it, not constructing another application instance.

Choose the relevant guide:
- **Create or change tasks/steps, context or control flow:** [authoring](references/authoring.md).
- **Run tasks, combinations, inspect failures or recover:** [execution](references/execution.md).
- **Prepare requirements and inspect/open evidence:** [acceptance](references/acceptance.md).

Discover summaries first. `discover(kind="operation", query=...)` lists actual operation names. `describe(kind="operation", identity=...)` returns the current parameter Schema. Fetch selected capabilities and immutable authoring materials before writing code. Keep code, full catalogs, screenshots and large results out of the conversation unless needed; page with returned cursors and select sections or JSON pointers.

Give each mutation a unique `request_id`; identical retries retain that ID. An uncertain receipt or UNKNOWN execution requires checking existing facts. Do not change IDs to force a repeated side effect. Fixed execution uses no model calls.

Report the task goal, concrete changes, tested paths, run ID, automatic checks, evidence limitations and human acceptance separately. An executed action's own `passed` value is a persisted step result; evaluate whether independent observation is needed. Only report human acceptance when a matching current human decision exists. Use `review(action="open", params={"kind":"run"|"sequence","identity":...})` to show evidence in the workbench.
