"""Plain interaction state; framework view handles live in desktop adapters."""

from dataclasses import dataclass, field
import asyncio
from copy import deepcopy


@dataclass
class PlanningPageState:
    plan_id: str | None = None
    search: str = ""
    generation: int = 0


@dataclass
class StepEditorState:
    task_id: str | None = None
    step_id: str | None = None
    old_step: dict | None = None
    generation: int = 0
    save_lock: object | None = None
    autosave_paused: bool = False
    reload_draft: dict | None = None
    reload_debug: dict | None = None
    draft: dict | None = None

    def capture_draft(self, values: dict) -> None:
        self.draft = deepcopy(values)

    def __post_init__(self):
        if self.save_lock is None:
            self.save_lock = asyncio.Lock()


@dataclass
class DebugState:
    run_id: str | None = None
    environment_id: str | None = None
    task_inputs: dict | None = None
    step_inputs: dict | None = None
    input_identity: tuple | None = None
    supplements: dict | None = None
    feedback: dict | None = None
    feedback_run_id: str | None = None
    removed_feedback: set | None = None
    trial_signature: str | None = None
    fresh_round: bool = False

    def __post_init__(self):
        self.supplements = dict(self.supplements or {})
        self.removed_feedback = set(self.removed_feedback or ())


@dataclass
class ExecutionPageState:
    task_ids: list[str] | None = None
    statuses: list[str] | None = None
    search_query: str = ""
    signature: object | None = None
    run_id: str | None = None
    run_signature: object | None = None
    selected_step_id: str | None = None
    selected_step_run_id: str | None = None

    def __post_init__(self):
        self.task_ids = list(self.task_ids or [])
        self.statuses = list(self.statuses or [])


@dataclass
class RunInputState:
    dialog_token: tuple | None = None
    drafts: dict = field(default_factory=dict)


@dataclass
class ContextPageState:
    entries: list[dict] | None = None
    ai_contexts: list[dict] | None = None

    def __post_init__(self):
        self.entries = list(self.entries or [])
        self.ai_contexts = list(self.ai_contexts or [])
