"""Framework-independent step authoring, evidence and adoption decisions."""
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, overload
from taskweave.core.data_contracts import StepRecord
from taskweave.core.json_types import JSON
import json
from taskweave.core.validation import TaskError, normalize_step
from taskweave.presentation.context_collection import context_ai_items

Identity = tuple[str | None, str | None, int, int]


class OperationPort(Protocol):
    @overload
    async def __call__(self, operation: Literal['run.get'], *, run_id: str) -> dict[str, JSON]: ...
    @overload
    async def __call__(self, operation: Literal['context.ai'], *, step_id: str) -> list[dict[str, JSON]]: ...
    @overload
    async def __call__(self, operation: Literal['step.confirm.manual'], *, step_id: str,
                       expected_hash: str, environment_id: str | None) -> StepRecord: ...


class ContentProposal(TypedDict):
    proposed_content: str
    explanation: str
    diagnostics: list[dict[str, JSON]]
    expected_hash: str
    stale: bool
    history_trimmed: bool
    authoring_session_id: str


class GoalProposal(TypedDict):
    step_description: str
    step_notes: str
    expected_hash: str


class _ChatProposalOptional(TypedDict, total=False):
    messages: list[dict[str, JSON]]
    history_trimmed: bool


class ChatProposal(_ChatProposalOptional):
    prompt: str
    attachments: list[dict[str, JSON]]
    expected_hash: str


class RequestPort(Protocol):
    @overload
    async def __call__(self, operation: Literal['step.generate'], saved: StepRecord, *,
                       step_id: str, expected_hash: str, step_description: str,
                       feedback: dict[str, JSON] | None, contexts: list[dict[str, JSON]],
                       environment_id: str | None, repair_notes: str,
                       use_history: bool, history_rounds: int, deduplicate_history: bool,
                       export_only: bool) -> ContentProposal | ChatProposal: ...
    @overload
    async def __call__(self, operation: Literal['step.generate_goal'], saved: StepRecord, *,
                       step_id: str, expected_hash: str, supplement: str,
                       contexts: list[dict[str, JSON]], environment_id: str | None,
                       export_only: bool) -> GoalProposal | ChatProposal: ...


@dataclass(frozen=True)
class Notice:
    code: str
    kind: str = 'info'


@dataclass(frozen=True)
class GenerationOutcome:
    candidate: tuple[dict, dict, Identity] | None = None
    notices: tuple[Notice, ...] = ()


@dataclass(frozen=True)
class ConfirmationDecision:
    status: Literal['confirmed', 'manual', 'stale', 'cancelled']
    saved: dict
    identity: Identity


class AuthoringFlow:
    def __init__(self, *, call: OperationPort, request: RequestPort,
                 identity: Callable[[], Identity], trials: Mapping[str, str],
                 trial_feedback: Callable[[str, str], Awaitable[dict]] | None = None,
                 repair_contexts: Callable[[dict, str, dict], Awaitable[tuple[list, dict]]] | None = None,
                 confirm: Callable[[dict, str], Awaitable[dict]] | None = None,
                 validate_step: Callable[[dict], Awaitable[list[dict]]] | None = None):
        self.call, self.request, self.identity, self.trials = call, request, identity, trials
        self.trial_feedback, self.repair_contexts, self.confirm = trial_feedback, repair_contexts, confirm
        self.validate_step = validate_step

    async def generate(self, saved: dict, identity: Identity, **options) -> GenerationOutcome:
        notices = []
        candidate = None
        async for event in self.generate_events(saved, identity, **options):
            if isinstance(event, Notice):
                notices.append(event)
            else:
                candidate = event.candidate
        return GenerationOutcome(candidate, tuple(notices))

    async def generate_events(self, saved: dict, identity: Identity, *, environment_id=None,
                       fix_logs=False, web_chat=False, supplement='', run_id=None,
                       history_rounds=None, deduplicate_history=True,
                       feedback_override=None, feedback_run_id=None, removed_feedback=()) -> AsyncIterator[Notice | GenerationOutcome]:
        if self.identity() != identity or saved["step_id"] != identity[1]:
            return
        trial = None
        feedback = None
        if fix_logs and feedback_override is not None and self.trials.get(saved['step_id']) != run_id:
            yield Notice('repair_changed', 'warning')
            return
        if fix_logs and run_id:
            trial = await self.call("run.get", run_id=run_id)
            if self.identity() != identity or (
                feedback_override is not None and self.trials.get(saved['step_id']) != run_id
            ):
                if feedback_override is not None:
                    yield Notice('repair_changed', 'warning')
                return
            failed = self.latest_failure(trial)
            if failed and failed['step_id'] == saved['step_id']:
                feedback = await self.trial_feedback(trial["run_id"], saved["step_id"])
                if feedback_override is not None and (
                    self.identity() != identity or self.trials.get(saved["step_id"]) != trial["run_id"]
                ):
                    yield Notice('repair_changed', 'warning')
                    return
                if self.identity() != identity:
                    return
                if feedback_override is not None:
                    bound_attempt_id = feedback_override.get("attempt_id")
                    current_attempt_id = failed.get("attempt_id") if failed and failed.get("step_id") == saved["step_id"] else None
                    refreshed_run_id = feedback.get("run_id") if isinstance(feedback, dict) else None
                    refreshed_attempt_id = feedback.get("attempt_id") if isinstance(feedback, dict) else None
                    if (
                        feedback_run_id != trial["run_id"]
                        or feedback_override.get("run_id") != trial["run_id"]
                        or trial.get("run_id") != run_id
                        or self.trials.get(saved["step_id"]) != trial["run_id"]
                        or not bound_attempt_id
                        or bound_attempt_id != current_attempt_id
                        or refreshed_run_id != trial["run_id"]
                        or refreshed_attempt_id != current_attempt_id
                        or refreshed_attempt_id != bound_attempt_id
                    ):
                        yield Notice('repair_changed', 'warning')
                        return
                    feedback = dict(feedback_override)
                for key in removed_feedback:
                    feedback.pop(key, None)
        if fix_logs and feedback_override and feedback is None:
            yield Notice('repair_changed', 'warning')
            return
        generation_contexts = context_ai_items(
            await self.call("context.ai", step_id=saved["step_id"])
        )
        if self.identity() != identity:
            return
        if feedback:
            refreshed, availability = await self.repair_contexts(saved, trial["run_id"], feedback)
            if self.identity() != identity:
                return
            if refreshed:
                generation_contexts.append({"provider_id": "debug.refresh", "name": "本次调试刷新",
                    "context_notes": "", "order_index": len(generation_contexts),
                    "captures": [{"label": "当前页面", "capture_index": 0, "items": refreshed}]})
            feedback["current_context_status"] = availability
            if not availability["available"]:
                yield Notice('context_unavailable', 'warning')
        yield Notice('preparing_chat' if web_chat else 'generating')
        proposal = await self.request(
            "step.generate", saved, step_id=saved["step_id"], expected_hash=saved["content_hash"],
            step_description=saved["step_description"], feedback=feedback, contexts=generation_contexts,
            environment_id=environment_id or None, repair_notes=supplement,
            use_history=fix_logs and history_rounds != 0,
            history_rounds=(-1 if fix_logs else 0) if history_rounds is None else history_rounds,
            deduplicate_history=deduplicate_history, export_only=web_chat,
        )
        if self.identity() != identity:
            return
        yield GenerationOutcome((saved, proposal, identity))


    async def generate_goal(self, saved: dict, identity: Identity, *, supplement: str,
                            environment_id: str | None, web_chat: bool) -> dict | None:
        contexts = context_ai_items(await self.call('context.ai', step_id=saved['step_id']))
        if self.identity() != identity:
            return None
        proposal = await self.request(
            'step.generate_goal', saved, step_id=saved['step_id'], expected_hash=saved['content_hash'],
            supplement=supplement, contexts=contexts,
            environment_id=environment_id or None, export_only=web_chat,
        )
        return proposal if self.identity() == identity else None

    async def confirm_saved(self, saved: dict, identity: Identity) -> ConfirmationDecision:
        if self.identity() != identity:
            return ConfirmationDecision('stale', saved, identity)
        run_id = self.trials.get(saved['step_id'])
        confirmed = None
        if run_id:
            try:
                confirmed = await self.confirm(saved, run_id)
            except TaskError as exc:
                if exc.code != 'VALIDATION_EVIDENCE_INVALID':
                    raise
        status = 'confirmed' if confirmed is not None else 'manual'
        return ConfirmationDecision(status if self.identity() == identity else 'stale', saved, identity)

    async def confirm_manual(self, decision: ConfirmationDecision, *, approved: bool,
                             environment_id: str | None) -> ConfirmationDecision:
        if self.identity() != decision.identity:
            return ConfirmationDecision('stale', decision.saved, decision.identity)
        if not approved:
            return ConfirmationDecision('cancelled', decision.saved, decision.identity)
        if decision.status != 'manual':
            return decision
        await self.call('step.confirm.manual', step_id=decision.saved['step_id'],
                        expected_hash=decision.saved['content_hash'], environment_id=environment_id or None)
        return ConfirmationDecision('confirmed' if self.identity() == decision.identity else 'stale',
                                    decision.saved, decision.identity)

    def content_candidate(self, saved: dict, proposal: dict, identity: Identity,
                          current_code: str | None) -> str:
        if self.identity() != identity or current_code is None:
            raise TaskError('EDIT_CONFLICT', '生成期间当前步骤已切换，请重新生成建议')
        if proposal['stale'] or current_code != saved['step_content']:
            raise TaskError('EDIT_CONFLICT', '生成期间内容已修改，请重新生成建议')
        return proposal['proposed_content']

    def validate_version(self, saved: dict, latest: dict, identity: Identity, *,
                         current_code: str | None, expected_hash: str) -> None:
        if (self.identity() != identity or current_code is None
                or latest['content_hash'] != expected_hash
                or current_code != saved['step_content']):
            raise TaskError('EDIT_CONFLICT', '步骤已修改，请重新生成网页对话内容')

    def goal_candidate(self, latest: dict, saved: dict, identity: Identity, *,
                       has_draft: bool, description: str, notes: str) -> dict:
        if self.identity() != identity or latest['content_hash'] != saved['content_hash'] or not has_draft:
            raise TaskError('EDIT_CONFLICT')
        return {'step_description': description, 'step_notes': notes}


    async def repair_evidence(self, identity: Identity, step_id: str, run_id: str | None) -> dict | None:
        if not run_id:
            return {}
        run = await self.call('run.get', run_id=run_id)
        if self.identity() != identity or self.trials.get(step_id) != run_id:
            return None
        failed = self.latest_failure(run)
        if failed is None or failed.get('step_id') != step_id:
            return {}
        feedback = await self.trial_feedback(run_id, step_id)
        if self.identity() != identity or self.trials.get(step_id) != run_id:
            return None
        if (feedback and feedback.get('run_id') == run_id
                and feedback.get('attempt_id') == failed.get('attempt_id')):
            return feedback
        return {}

    async def recheck_repair(self, identity: Identity, step_id: str, run_id: str,
                             feedback: dict) -> str:
        run = await self.call('run.get', run_id=run_id)
        if self.identity() != identity or self.trials.get(step_id) != run_id:
            return 'stale'
        failed = self.latest_failure(run)
        if (failed is None or failed.get('step_id') != step_id
                or failed.get('attempt_id') != feedback.get('attempt_id')):
            return 'changed'
        return 'current'

    @staticmethod
    def latest_failure(run: dict) -> dict | None:
        return next((attempt for attempt in reversed(run.get('attempts', []))
                     if attempt.get('valid') and attempt.get('status') in {'FAILED', 'UNKNOWN'}), None)


    async def validate_web_candidate(self, saved: dict, source: str, identity: Identity) -> list[dict] | None:
        candidate = normalize_step({**saved, 'step_content': source})
        diagnostics = await self.validate_step(candidate)
        if self.identity() != identity:
            return None
        errors = [item.get('message', '') for item in diagnostics if item.get('severity') == 'error']
        if errors:
            raise TaskError('CHAT_REPLY_INVALID', '；'.join(errors))
        return diagnostics


@dataclass
class AIChoiceDraft:
    """Dialog-independent values and one accepted channel selection."""
    identity: Identity
    supplement: str = ''
    history_rounds: int = -1
    deduplicate: bool = True
    reply: str = ''
    submitted: bool = False

    def submit(self, channel: str, current_identity: Identity) -> tuple[str, int, bool, str] | None:
        if self.submitted or current_identity != self.identity:
            return None
        self.submitted = True
        return channel, self.history_rounds, self.deduplicate, self.supplement

    def parse_content(self) -> tuple[str, str]:
        from taskweave.presentation.chat import parse_chat_reply
        return parse_chat_reply(self.reply)

    def parse_goal(self) -> tuple[str, str]:
        from taskweave.presentation.chat import parse_goal_reply
        return parse_goal_reply(self.reply)


class AIInteraction:
    """Own the local modal flow; accepted background requests remain application-owned."""
    def __init__(self):
        self.active = False
        self.pending_identity: Identity | None = None

    def begin(self, *, retained_pending: bool = False, recovering: bool = False) -> str | None:
        if self.active:
            return 'flow_active'
        if retained_pending and not recovering:
            return 'request_pending'
        self.active = True
        return None

    def finish(self) -> None:
        self.active = False

    def choice(self, identity: Identity, *, supplement: str = '') -> AIChoiceDraft:
        return AIChoiceDraft(identity, supplement=supplement)

    @staticmethod
    def clear_repair(debug, step_id: str) -> None:
        debug.supplements.pop(step_id, None)
        debug.feedback = None
        debug.feedback_run_id = None
        debug.removed_feedback.clear()
