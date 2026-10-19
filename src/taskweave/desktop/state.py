"""Compatibility state types with NiceGUI-only view handles."""
from dataclasses import dataclass
from taskweave.presentation import state as interaction
from taskweave.presentation.state import DebugState, ContextPageState

class PlanningPageState:
    """Desktop save action plus one plain planning selection state."""
    def __init__(self, plan_id=None, search="", generation=0, save_callback=None):
        self.interaction = interaction.PlanningPageState(plan_id, search, generation)
        self.save_callback = save_callback

    @property
    def plan_id(self): return self.interaction.plan_id
    @plan_id.setter
    def plan_id(self, value): self.interaction.plan_id = value

    @property
    def search(self): return self.interaction.search
    @search.setter
    def search(self, value): self.interaction.search = value

    @property
    def generation(self): return self.interaction.generation
    @generation.setter
    def generation(self, value): self.interaction.generation = value


class StepEditorState:
    """Legacy desktop field access forwards to one plain editor state."""
    def __init__(self, task_id=None, step_id=None, old_step=None, edit_controls=None,
                 generation=0, save_lock=None, autosave_paused=False, reload_draft=None,
                 reload_debug=None, draft=None):
        self.interaction = interaction.StepEditorState(
            task_id=task_id, step_id=step_id, old_step=old_step, generation=generation,
            save_lock=save_lock, autosave_paused=autosave_paused, reload_draft=reload_draft,
            reload_debug=reload_debug, draft=draft)
        self.edit_controls = edit_controls

    def capture_draft(self, values):
        self.interaction.capture_draft(values)

    @property
    def task_id(self): return self.interaction.task_id
    @task_id.setter
    def task_id(self, value): self.interaction.task_id = value

    @property
    def step_id(self): return self.interaction.step_id
    @step_id.setter
    def step_id(self, value): self.interaction.step_id = value

    @property
    def old_step(self): return self.interaction.old_step
    @old_step.setter
    def old_step(self, value): self.interaction.old_step = value

    @property
    def generation(self): return self.interaction.generation
    @generation.setter
    def generation(self, value): self.interaction.generation = value

    @property
    def save_lock(self): return self.interaction.save_lock
    @save_lock.setter
    def save_lock(self, value): self.interaction.save_lock = value

    @property
    def autosave_paused(self): return self.interaction.autosave_paused
    @autosave_paused.setter
    def autosave_paused(self, value): self.interaction.autosave_paused = value

    @property
    def reload_draft(self): return self.interaction.reload_draft
    @reload_draft.setter
    def reload_draft(self, value): self.interaction.reload_draft = value

    @property
    def reload_debug(self): return self.interaction.reload_debug
    @reload_debug.setter
    def reload_debug(self, value): self.interaction.reload_debug = value

    @property
    def draft(self): return self.interaction.draft
    @draft.setter
    def draft(self, value): self.interaction.draft = value

class ExecutionPageState:
    """Plain execution state owns selections; this adapter owns view handles."""
    def __init__(self, task_ids=None, statuses=None, search_query="", signature=None,
                 run_id=None, run_signature=None, selected_step_id=None,
                 selected_step_run_id=None, execution_rows=None, execution_list_area=None,
                 run_area=None, countdown_label=None):
        self.interaction = interaction.ExecutionPageState(
            task_ids=task_ids, statuses=statuses, search_query=search_query,
            signature=signature, run_id=run_id, run_signature=run_signature,
            selected_step_id=selected_step_id, selected_step_run_id=selected_step_run_id)
        self.execution_rows, self.execution_list_area = execution_rows, execution_list_area
        self.run_area, self.countdown_label = run_area, countdown_label

    @property
    def task_ids(self): return self.interaction.task_ids
    @task_ids.setter
    def task_ids(self, value): self.interaction.task_ids = value

    @property
    def statuses(self): return self.interaction.statuses
    @statuses.setter
    def statuses(self, value): self.interaction.statuses = value

    @property
    def search_query(self): return self.interaction.search_query
    @search_query.setter
    def search_query(self, value): self.interaction.search_query = value

    @property
    def signature(self): return self.interaction.signature
    @signature.setter
    def signature(self, value): self.interaction.signature = value

    @property
    def run_id(self): return self.interaction.run_id
    @run_id.setter
    def run_id(self, value): self.interaction.run_id = value

    @property
    def run_signature(self): return self.interaction.run_signature
    @run_signature.setter
    def run_signature(self, value): self.interaction.run_signature = value

    @property
    def selected_step_id(self): return self.interaction.selected_step_id
    @selected_step_id.setter
    def selected_step_id(self, value): self.interaction.selected_step_id = value

    @property
    def selected_step_run_id(self): return self.interaction.selected_step_run_id
    @selected_step_run_id.setter
    def selected_step_run_id(self, value): self.interaction.selected_step_run_id = value

@dataclass
class RunInputState(interaction.RunInputState):
    dialog: object | None = None
