# UI assertion migration map

The following legacy source-string checks were replaced with assertions on values,
callbacks, rendered controls, and controller-visible behavior:

| Previous assertion | Behavioral replacement |
| --- | --- |
| `tests.test_workbench_changes.WorkbenchChanges.test_step_reorder_uses_local_motion_instead_of_page_repaint` | `tests.ui.test_step_list.StepListTests.test_adjacent_reorder_persists_then_moves_existing_controls`; verifies controller ordering, order/labels, and DOM control movement. |
| `tests.test_workbench_changes.WorkbenchChanges.test_planning_ui_uses_planning_copy_chips_and_saves_before_actions` | `test_planning_actions_save_draft_before_dependent_workflow` and `tests.test_planning.PlanningTests.test_plan_list_has_search_and_delete_without_result_count`; checks callback order and rendered search/copy/delete controls. |
| `tests.test_workbench_changes.WorkbenchChanges.test_step_plugin_collection_has_optional_advanced_json_override` | `test_context_request_merges_form_advanced_and_target_values_in_order` plus `test_recollection_advanced_json_keeps_only_non_form_parameters`; checks schema filtering and actual merge precedence. |
| `tests.test_planning.PlanningTests.test_plan_list_has_search_and_delete_without_result_count` | Same test name; now renders a populated PlanningPage and checks visible labels and delete control props. |
| `tests.test_planning.PlanningTests.test_plan_context_dialog_is_plugin_schema_driven` | Same test name; now exercises target parameter hiding and surface defaults against a plugin request schema. |
| `tests.test_input_ui.InputUi.test_dependency_picker_and_task_then_step_input` legacy export-format assertion | Same browser flow now checks the established `taskweave-task-2` format from `core/task_package.py`; the v1 compatibility rejection remains covered by `tests.test_task_transfer.TaskTransfer.test_v1_requires_reexport`. |

These methods are discovered once by unittest. No source-string assertion was kept
as a duplicate of the behavioral replacement.
