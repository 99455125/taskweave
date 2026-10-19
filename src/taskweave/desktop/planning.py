"""Compatibility imports for the planning page, now owned by pages.planning."""
from nicegui import ui
from taskweave.desktop.pages.planning import (
    PlanningPage, filter_plans, next_plan_id, mutate_planning_capture,
    _refresh_organization_controls_for_view,
)
from taskweave.desktop.components.planning_generations import (
    generation_summary, short_updated_at, candidate_step_rows,
    GENERATION_CHANNEL_LABELS, GENERATION_STATUS_LABELS,
)
