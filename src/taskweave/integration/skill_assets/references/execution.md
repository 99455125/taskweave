# Execute and recover

Discover the task/sequence, describe its current version, inputs, confirmation state and environment. Discover/describe the chosen execute operation. Prepare acceptance requirements for this version if the user has criteria.

For one-call task execution use `execute(operation="task.run", params={task_id:..., expected_hash:..., inputs:{...}}, request_id=..., review_spec_id=...)`. For advanced modes, use `run.create` then `run.start`. For combinations describe the current revision and member definitions, prepare requirements for that version, then use `sequence.start` with optional `review_spec_id`. Read actual required fields from operation Schema. This reuses native input, validation, confirmation, worker, pause and recovery rules.

Use `wait(identity=..., kind="run"|"sequence", timeout=30)` for a compact response. Missing inputs require user-provided values or authorized data, including valid zero/false values. Discover `run.inputs` or `sequence.run.inputs`; task input submission continues the original requested mode. Inspect run/sequence status before deciding what to do next.

Evidence reads:
- `inspect(kind="run", identity=..., sections=["attempts"|"flow"|"results"])` pages persisted facts.
- `inspect(kind="output", identity=run_id, step_id=..., pointer=...)` reads aggregate output; `execution_path` selects one exact instance. Nested-loop item projection may need `item_pointer` and `loop_node_id`. Read current operation/material contracts rather than reconstructing outputs from the last successful attempt.
- `inspect(kind="result", identity=result_id)` reads selected saved evidence; images require explicit `include_images=true`.
- `inspect(kind="request", identity=request_id)` checks a durable receipt. Use a pointer to retrieve a selected saved result when a response exceeded the inline budget. A receipt is not proof that external effects did or did not happen.
- `inspect(kind="operation_result", identity=operation_name, params={...}, pointer=...)` executes other discovered read operations, such as plan.generation.get/list/imports, draft.export and feedback.export. Operation Schema determines params; this path rejects mutations.
- Large bundles/results accept pointer. A large object returns child pointers; a large text returns text, fingerprint and next_offset. Continue with the same pointer and text_offset=next_offset until null, then join in order. This reads the frozen value losslessly without sending unrelated sections.

For FAILED inspect the failed valid attempt and error evidence. For UNKNOWN/interrupted effects, first identify the exact attempt/execution path, then check the external target or ask the user for evidence. Get `run.reconcile`/`sequence.run.reconcile` contracts and applicable decisions; reconcile only what the evidence establishes. If completion cannot be established, report the uncertainty and obtain the needed human decision. Do not automatically declare an action unexecuted, start a new run or retry with a new request ID. Pending unsafe commands remain uncertain rather than being resent automatically.

Pause/cancel/retry are explicit user-goal decisions. They can affect live external systems. After a legitimate retry inspect the new attempt and keep prior attempts visible as history.
