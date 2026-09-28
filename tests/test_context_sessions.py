import asyncio
import base64
import tempfile
import unittest
from taskweave.application.planning import PlanningService
from taskweave.core.ports import AuthoringContribution, ContextCollection, ContextItem, ContextView
from taskweave.core.validation import TaskError
from taskweave.infrastructure.context_sessions import ContextSessions
from taskweave.infrastructure.plan_repository import PlanRepository
from taskweave.infrastructure.repository import Repository


class Provider:
    def __init__(self): self.opens = self.closes = 0
    async def open(self, ctx, role): self.opens += 1; return {"value": "kept"}
    async def close(self, resource): self.closes += 1


class Plugin:
    def manifest(self): return {"id": "fake"}
    def authoring(self, capabilities): return AuthoringContribution("", context_provider_ids=("fake.page",))
    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        value = await ctx.resources.acquire("fake.browser", request.get("role", "main"))
        if request.get("secret_evidence"):
            return ContextCollection((ContextItem("text", "text/plain", request["secret_evidence"], "fake"),))
        if include_view and request.get("image_base64"):
            return ContextCollection(
                (ContextItem("text", "text/plain", "page evidence " * 6000, "fake"),),
                (ContextView("页面", "fake.image", {"image_base64": request["image_base64"], "mime_type": "image/png"}),),
            )
        return ContextCollection((ContextItem("text", "text/plain", value["value"], "fake"),))

    async def list_context_targets(self, provider_id, ctx, request):
        return [{"target_id": role, "label": role, "request": {"role": role}}
                for role, _ in ctx.resources.active("fake.browser")]


class Registry:
    def __init__(self, provider):
        self.plugins = [Plugin()]
        self.providers = {"fake.browser": provider}
        self.views = {"fake.image": {"type": "image"}}


class ContextSessionTests(unittest.TestCase):
    @staticmethod
    def planning_service(plans, sessions, registry, uow):
        from pathlib import Path
        return PlanningService(plans, None, None, sessions, None, registry, None, None, None, None, None, uow, Path("."))

    def test_planning_service_collection_operation_is_read_only(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); registry = Registry(Provider())
            sessions = ContextSessions(registry, repo, plans, repo.home / "plans")
            self.addCleanup(sessions.close)
            plan = plans.create('P')
            plan = plans.update(plan['plan_id'], plan['revision'], 'P', plugin_ids=['fake'])
            service = self.planning_service(plans, sessions, registry, repo.unit_of_work)
            result = service.context_collect(plan_id=plan['plan_id'], expected_revision=plan['revision'], provider_id='fake.page')
            self.assertIn('capture', result)
            self.assertNotIn('plan', result)
            self.assertEqual(plans.get(plan['plan_id'])['revision'], plan['revision'])
            self.assertEqual(plans.contexts(plan['plan_id']), [])

    def test_plan_collection_returns_original_sensitive_evidence_without_saving(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home)
            plans = PlanRepository(repo)
            sessions = ContextSessions(Registry(Provider()), repo, plans, repo.home / "plans")
            self.addCleanup(sessions.close)
            plan = plans.create("原文保存")
            plan = plans.update(plan["plan_id"], plan["revision"], "原文保存", plugin_ids=["fake"])
            result = sessions.collect(plan["plan_id"], plan["revision"], "fake.page", {"secret_evidence": "password=abcd1234"})
            self.assertEqual(result['capture']['items'][0]['content'], "password=abcd1234")
            self.assertEqual(plans.contexts(plan["plan_id"]), [])

    def test_plan_collection_returns_complete_preview_image_without_saving(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home)
            plans = PlanRepository(repo)
            sessions = ContextSessions(Registry(Provider()), repo, plans, repo.home / "plans")
            self.addCleanup(sessions.close)
            plan = plans.create("预览")
            plan = plans.update(plan["plan_id"], plan["revision"], "预览", plugin_ids=["fake"])
            encoded = base64.b64encode(b"capture" * 10000).decode("ascii")
            collected = sessions.collect(plan["plan_id"], plan["revision"], "fake.page", {"image_base64": encoded})
            self.assertEqual(collected['capture']['views'][0]['data']['image_base64'], encoded)
            self.assertGreater(len(collected['capture']['items'][0]['content']), 65536)
            self.assertEqual(PlanRepository(Repository(home)).contexts(plan["plan_id"]), [])

    def test_busy_configuration_change_and_stale_delete_preserve_plan_session(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); provider = Provider()
            registry = Registry(provider)
            sessions = ContextSessions(registry, repo, plans, repo.home / "plans")
            self.addCleanup(sessions.close)
            service = self.planning_service(plans, sessions, registry, repo.unit_of_work)
            plan = plans.create("P")
            plan = plans.update(plan["plan_id"], 1, "P", plugin_ids=["fake"])
            collected = sessions.collect(plan["plan_id"], 2, "fake.page")
            self.assertNotIn('plan', collected)
            session = sessions.sessions[plan["plan_id"]]
            session.busy.acquire()
            try:
                with self.assertRaises(TaskError) as busy:
                    service.update(plan_id=plan["plan_id"], expected_revision=plan["revision"], name="P", plugin_ids=[])
                self.assertEqual(busy.exception.code, "CONTEXT_SESSION_BUSY")
                self.assertEqual(plans.get(plan["plan_id"])["plugin_ids"], ["fake"])
                self.assertEqual(plans.get(plan["plan_id"])["revision"], 2)
            finally:
                session.busy.release()
            with self.assertRaises(TaskError) as stale:
                service.delete(plan["plan_id"], plan["revision"] - 1)
            self.assertEqual(stale.exception.code, "EDIT_CONFLICT")
            self.assertEqual(sessions.list()[0]["session_id"], session.session_id)
            self.assertEqual(provider.closes, 0)

    def test_targets_only_list_existing_resources_and_reject_replaced_session(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); provider = Provider()
            sessions = ContextSessions(Registry(provider), repo, plans, repo.home / "plans")
            self.addCleanup(sessions.close)
            plan = plans.create("P")
            plan = plans.update(plan["plan_id"], 1, "P", plugin_ids=["fake"])
            self.assertEqual(sessions.targets(plan["plan_id"], "fake.page"), {"session_id": None, "targets": []})
            self.assertEqual(provider.opens, 0)
            self.assertEqual(sessions.list(), [])
            collected = sessions.collect(plan["plan_id"], 2, "fake.page", {"role": "second"})
            available = sessions.targets(plan["plan_id"], "fake.page")
            self.assertEqual(available["targets"], [{"target_id": "second", "label": "second", "request": {"role": "second"}}])
            self.assertEqual(provider.opens, 1)
            sessions.end(plan["plan_id"])
            with self.assertRaises(TaskError) as stale:
                sessions.collect(plan["plan_id"], 2, "fake.page", expected_session_id=available["session_id"])
            self.assertEqual(stale.exception.code, "CONTEXT_SESSION_CHANGED")
            self.assertEqual(provider.opens, 1)
            self.assertEqual(sessions.list(), [])

    def test_end_busy_session_preserves_it_and_old_plugin_has_no_targets(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); provider = Provider()
            registry = Registry(provider)
            registry.plugins[0].list_context_targets = None
            sessions = ContextSessions(registry, repo, plans, repo.home / "plans")
            self.addCleanup(sessions.close)
            plan = plans.create("P")
            plan = plans.update(plan["plan_id"], 1, "P", plugin_ids=["fake"])
            sessions.collect(plan["plan_id"], 2, "fake.page")
            available = sessions.targets(plan["plan_id"], "fake.page")
            self.assertEqual(available["targets"], [])
            self.assertTrue(available["session_id"])
            session = sessions.sessions[plan["plan_id"]]
            session.busy.acquire()
            try:
                with self.assertRaises(TaskError) as busy:
                    sessions.end(plan["plan_id"])
                self.assertEqual(busy.exception.code, "CONTEXT_SESSION_BUSY")
                self.assertEqual(sessions.list()[0]["session_id"], available["session_id"])
            finally:
                session.busy.release()
            sessions.end(plan["plan_id"])
            self.assertEqual(provider.closes, 1)

    def test_same_plan_reuses_resource_and_end_closes_once(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); provider = Provider()
            sessions = ContextSessions(Registry(provider), repo, plans, repo.home / "plans")
            plan = plans.create("P")
            plan = plans.update(plan["plan_id"], 1, "P", plugin_ids=["fake"])
            first = sessions.collect(plan["plan_id"], 2, "fake.page")
            second = sessions.collect(plan["plan_id"], 2, "fake.page")
            self.assertEqual(provider.opens, 1)
            self.assertEqual(len(plans.contexts(plan["plan_id"])), 0)
            sessions.end(plan["plan_id"])
            self.assertEqual(provider.closes, 1)
