"""Shared staged recording: successful persistence precedes consumption."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from taskweave.core.validation import TaskError
from taskweave.desktop.contexts import ContextCaptureDraft
from tests.test_context_recording_runtime import RecordingPlugin
from taskweave.plugins.registry import Registry


class UIRecordingPlugin(RecordingPlugin):
    def manifest(self):
        return {**super().manifest(),'context_requests':{'demo.page':{'type':'object','properties':{'note':{'type':'string','default':'fixture'}},
                'x-taskweave-context-recording':True}}}

    async def record_context(self, provider_id, ctx, command, request, *, include_view=True):
        if command.operation=='pause': self.state='PAUSED'
        elif command.operation=='resume': self.state='RECORDING'
        return await super().record_context(provider_id,ctx,command,request,include_view=include_view)


def build_registry(): return Registry([UIRecordingPlugin()])


class RecordingDraftTests(unittest.TestCase):
    def test_changed_step_capabilities_do_not_strand_pending_recording_controls(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.components.step_contexts import StepContextPanel
        from taskweave.desktop.state import ContextPageState

        async def scenario(app, client):
            with client:
                controller = DesktopController(app)
                task = app.repo.create_task('Capability change recording')['task_id']
                step = app.repo.save_step(task, {'name': 'Observe', 'capabilities': ['demo.echo']})
                async def save_editor():
                    return app.repo.step(step['step_id'])
                panel = StepContextPanel(controller, ContextPageState(), lambda: step['step_id'],
                    None, None, None, None, save_editor=save_editor,
                    plugin_contributions=controller.plugin_contributions, task_id=lambda: task,
                    environment_id=lambda: None, button=lambda title, cb, **kw: ui.button(title, on_click=cb))
                await panel.collect()
                workspace = controller._collection_workspaces[('step', step['step_id'], None)]
                await workspace.recording.start({'provider_id': 'demo.page', 'request': {}}, include_view=False)
                recording_id = workspace.recording.recording_id
                workspace.dialog.close()
                await workspace.hide()
                changed = app.repo.step(step['step_id'])
                app.repo.save_step(task, {**changed, 'capabilities': []}, step_id=step['step_id'],
                                  expected_hash=changed['content_hash'])
                await panel.collect()
                self.assertTrue(workspace.dialog.value)
                self.assertEqual(workspace.recording.recording_id, recording_id)
                provider = next(el for el in workspace.dialog.descendants() if el._props.get('label') == '插件上下文')
                self.assertEqual(provider.value, 'demo.page')
                self.assertFalse(provider.enabled)
                self.assertTrue(any(getattr(el, 'text', '') == '停止并暂存' and el.visible
                                    for el in workspace.dialog.descendants()))
                start = next(el for el in workspace.dialog.descendants() if getattr(el, 'text', '') == '开始录制')
                controls = next(event.handler for event in start._event_listeners.values() if event.type == 'click').__self__
                await controls.run(workspace.recording.stage)
                self.assertEqual(workspace.recording.state, 'STOPPED')
                self.assertTrue(workspace.recording.pending)
                entry = workspace.recording.entry
                save = next(el for el in workspace.dialog.descendants() if getattr(el, 'text', '') == '确认保存')
                with patch.object(ui, 'notify') as notify:
                    await next(event.handler for event in save._event_listeners.values() if event.type == 'click')()
                self.assertTrue(notify.called)
                self.assertIs(workspace.recording.entry, entry)
                self.assertTrue(workspace.recording.pending)
                self.assertFalse(workspace.recording.committed)
                self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']}), [])
                await controls.run(workspace.recording.discard)
                self.assertFalse(workspace.recording.pending)
                self.assertFalse(controls.area.visible)
                capture = next(el for el in workspace.dialog.descendants() if getattr(el, 'text', '') == '采集一项')
                self.assertFalse(capture.enabled)
                self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']}), [])

        with tempfile.TemporaryDirectory() as home, Application(home, registry_factory=f'{__name__}:build_registry') as app:
            client = Client(page('/recording-changed-capabilities'))
            try:
                def capture_click(button, callback):
                    button.on('click', callback)
                    return button
                with patch.object(ui.button, 'on_click', capture_click):
                    asyncio.run(scenario(app, client))
            finally:
                client.delete()

    def test_reloaded_client_rebuilds_dialog_and_preserves_recording_draft(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.planning import PlanningPage
        from taskweave.desktop.components.step_contexts import StepContextPanel
        from taskweave.desktop.state import PlanningPageState, ContextPageState
        async def scenario(app, first, replacement):
            controller=DesktopController(app)
            plan=app.dispatch('plan.create',{'name':'Reload recording'})
            plan=app.dispatch('plan.update',{'plan_id':plan['plan_id'],'expected_revision':plan['revision'],
                'name':plan['name'],'plugin_ids':['demo']})
            task=app.repo.create_task('Reload step')['task_id']
            step=app.repo.save_step(task,{'name':'Observe','capabilities':['demo.echo']})
            planning=PlanningPage(controller,PlanningPageState(),lambda title,cb,**kw:ui.button(title,on_click=cb),
                lambda:None,lambda *args,**kwargs:None,lambda *args:None)
            async def save_editor(): return app.repo.step(step['step_id'])
            panel=StepContextPanel(controller,ContextPageState(),lambda:step['step_id'],None,None,None,None,
                save_editor=save_editor,plugin_contributions=controller.plugin_contributions,
                task_id=lambda:task,environment_id=lambda:None,
                button=lambda title,cb,**kw:ui.button(title,on_click=cb))
            for open_dialog,key in [(lambda:planning.collect_dialog(plan),('plan',plan['plan_id'],None)),
                                    (lambda:panel.collect(),('step',step['step_id'],None))]:
                with first:
                    await open_dialog()
                    workspace=controller._collection_workspaces[key]
                    old=workspace.dialog
                    old_hide=next(listener.handler for listener in old._event_listeners.values() if listener.type=='hide')
                    name=next(e for e in old.descendants() if e._props.get('label')=='上下文名称')
                    name.value='刷新前尚未关闭弹窗的中文草稿'
                    await workspace.recording.start({'provider_id':'demo.page','request':{}},include_view=False)
                    recording_id=workspace.recording.recording_id
                with replacement:
                    await open_dialog()
                    self.assertIs(workspace.dialog.client,replacement)
                    self.assertIsNot(workspace.dialog,old)
                    self.assertTrue(old.is_deleted)
                    self.assertEqual(workspace.recording.recording_id,recording_id)
                    self.assertEqual(workspace.recording.state,'PAUSED')
                    restored=next(e for e in workspace.dialog.descendants() if e._props.get('label')=='上下文名称')
                    self.assertEqual(restored.value,'刷新前尚未关闭弹窗的中文草稿')
                    workspace.fields['name']='新页面已经更新的草稿'
                    await old_hide()
                    self.assertEqual(workspace.fields['name'],'新页面已经更新的草稿')
                    await workspace.recording.discard()
        with tempfile.TemporaryDirectory() as home,Application(home,registry_factory=f'{__name__}:build_registry') as app:
            first=Client(page('/recording-before-reload'));replacement=Client(page('/recording-after-reload'))
            try: asyncio.run(scenario(app,first,replacement))
            finally: first.delete();replacement.delete()

    def test_inflight_collection_cannot_be_rebound_to_another_client(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from taskweave.desktop.context_recording import collection_workspace
        async def scenario():
            workspace=collection_workspace(SimpleNamespace(),('step','s',None),[])
            old=SimpleNamespace(client=object(),value=True,is_deleted=False)
            workspace.dialog=old
            workspace.capture_fields=Mock()
            workspace.busy=True
            with self.assertRaises(TaskError) as error:
                await workspace.prepare_dialog(object())
            self.assertEqual(error.exception.code,'CONTEXT_SESSION_BUSY')
            self.assertIs(workspace.dialog,old)
            workspace.capture_fields.assert_not_called()
        asyncio.run(scenario())

    def test_planning_and_step_dialogs_commit_recording_via_same_controls(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.planning import PlanningPage
        from taskweave.desktop.components.step_contexts import StepContextPanel
        from taskweave.desktop.state import PlanningPageState, ContextPageState
        from unittest.mock import patch
        import inspect
        async def scenario(app,client):
            with client:
                controller=DesktopController(app)
                callbacks={}
                original=ui.button
                def button(text='',*args,**kwargs):
                    if kwargs.get('on_click'): callbacks[text]=kwargs['on_click']
                    return original(text,*args,**kwargs)
                async def click(text):
                    result=callbacks[text]()
                    if inspect.isawaitable(result): await result
                plan=app.dispatch('plan.create',{'name':'Dialog recording'})
                plan=app.dispatch('plan.update',{'plan_id':plan['plan_id'],'expected_revision':plan['revision'],
                    'name':plan['name'],'plugin_ids':['demo']})
                task=app.repo.create_task('Step recording')['task_id']
                step=app.repo.save_step(task,{'name':'Observe','capabilities':['demo.echo']})
                planning=PlanningPage(controller,PlanningPageState(),lambda title,cb,**kw:ui.button(title,on_click=cb),
                    lambda:None,lambda *args,**kwargs:None,lambda *args:None)
                async def save_editor(): return app.repo.step(step['step_id'])
                state=ContextPageState()
                panel=StepContextPanel(controller,state,lambda:step['step_id'],None,None,None,None,
                    save_editor=save_editor,plugin_contributions=controller.plugin_contributions,
                    task_id=lambda:task,environment_id=lambda:None,
                    button=lambda title,cb,**kw:ui.button(title,on_click=cb))
                for open_dialog,key,save_operation,list_operation,arguments in [
                    (lambda:planning.collect_dialog(plan),('plan',plan['plan_id'],None),'save_context_batch','plan.context.list',{'plan_id':plan['plan_id']}),
                    (lambda:panel.collect(),('step',step['step_id'],None),'save_step_context_batch','context.list',{'step_id':step['step_id']})]:
                    with patch('nicegui.ui.button',side_effect=button):
                        await open_dialog()
                        workspace=controller._collection_workspaces[key]
                        await click('开始录制')
                        self.assertTrue(workspace.recording.pending)
                        name=next(element for element in workspace.dialog.descendants() if element._props.get('label')=='上下文名称')
                        name.value='关闭后保留的长中文标题'
                        workspace.dialog.close()
                        hide=next(listener for listener in workspace.dialog._event_listeners.values() if listener.type=='hide')
                        await hide.handler()
                        self.assertEqual(workspace.recording.state,'PAUSED')
                        await open_dialog()
                        self.assertIs(controller._collection_workspaces[key],workspace)
                        name=next(element for element in workspace.dialog.descendants() if element._props.get('label')=='上下文名称')
                        self.assertEqual(name.value,'关闭后保留的长中文标题')
                        await click('暂停录制')
                        self.assertEqual(workspace.recording.state,'RECORDING')
                        await click('暂停录制')
                        self.assertEqual(workspace.recording.state,'PAUSED')
                        await click('停止并暂存')
                        self.assertEqual(len(workspace.draft.entries),1)
                        self.assertFalse(workspace.draft.entries[0]['send_preview'])
                        repository=app.planning.contexts if key[0]=='plan' else app.contexts.contexts
                        with patch.object(repository,save_operation,side_effect=RuntimeError('save failed')):
                            await click('确认保存')
                        self.assertTrue(workspace.recording.pending)
                        self.assertFalse(workspace.recording.committed)
                        real_call=controller.call
                        saves=[]
                        async def fail_ack(operation,**options):
                            if operation.endswith('save_batch'): saves.append(operation)
                            if operation.endswith('.record') and options.get('operation')=='ack':
                                raise RuntimeError('ack unavailable')
                            return await real_call(operation,**options)
                        with patch.object(controller,'call',side_effect=fail_ack):
                            await click('确认保存')
                        self.assertTrue(workspace.recording.committed)
                        self.assertTrue(workspace.recording.pending)
                        self.assertFalse(name.enabled)
                        with patch.object(controller,'call',wraps=real_call) as retry:
                            await click('确认保存')
                            self.assertFalse(any(call.args[0].endswith('save_batch') for call in retry.call_args_list))
                        self.assertEqual(len(saves),1)
                        self.assertFalse(workspace.recording.pending)
                        self.assertNotIn(key,controller._collection_workspaces)
                        self.assertEqual(len(app.dispatch(list_operation,arguments)),1)
                        existing=app.dispatch(list_operation,arguments)[0]
                        if key[0]=='plan': await planning.collect_dialog(plan,existing=existing)
                        else: await panel.collect(existing=existing)
                        editing=controller._collection_workspaces[(*key[:2],existing['context_id'])]
                        await click('开始录制')
                        await click('确认保存')
                        self.assertTrue(editing.dialog.value)
                        self.assertTrue(editing.recording.pending)
                        await editing.recording.discard()
        with tempfile.TemporaryDirectory() as home,Application(home,registry_factory=f'{__name__}:build_registry') as app:
            client=Client(page('/recording-dialogs'))
            try: asyncio.run(scenario(app,client))
            finally: client.delete()

    def test_closed_collection_workspace_restores_same_recording_and_fields(self):
        from taskweave.desktop.context_recording import collection_workspace
        from types import SimpleNamespace
        async def scenario():
            owner=SimpleNamespace()
            first=collection_workspace(owner,('step','s',None),[])
            first.fields.update(name='中文标题',notes='长操作说明',provider='p')
            async def invoke(operation,**options):
                return {'recording_id':'r','session_id':'instance','state':'PAUSED' if operation=='pause' else 'RECORDING','cursor':0}
            first.bind(invoke,source_page='draft')
            await first.recording.start({'provider_id':'p','request':{}},include_view=False)
            await first.hide()
            restored=collection_workspace(owner,('step','s',None),[])
            self.assertIs(restored,first)
            self.assertEqual(restored.recording.state,'PAUSED')
            self.assertEqual(restored.fields['name'],'中文标题')
            other=collection_workspace(owner,('step','another',None),[])
            self.assertIsNot(other,first)
        asyncio.run(scenario())

    def test_save_without_commit_result_keeps_evidence_for_retry(self):
        from taskweave.desktop.context_recording import RecordingDraft
        async def scenario():
            operations=[]
            async def invoke(operation, **options):
                operations.append(operation)
                return {'recording_id':'r','session_id':'s','state':'STOPPED','cursor':1,
                    'has_more':False,'capture':{'items':[{'kind':'text','content':'evidence'}],'views':[]}}
            state=RecordingDraft(ContextCaptureDraft(),invoke)
            await state.start({'request':{}},include_view=False)
            await state.stage()
            async def stale_save(): return None
            with self.assertRaises(TaskError): await state.persist(stale_save)
            self.assertTrue(state.pending)
            self.assertFalse(state.committed)
            self.assertNotIn('ack',operations)
            async def save(): return {'group':{'id':'saved'}}
            await state.persist(save)
            self.assertFalse(state.pending)
        asyncio.run(scenario())

    def test_committed_group_cannot_be_discarded_after_ack_failure(self):
        from taskweave.desktop.context_recording import RecordingDraft
        async def scenario():
            operations=[]
            async def invoke(operation, **options):
                operations.append(operation)
                if operation=='ack': raise RuntimeError('connection lost')
                return {'recording_id':'r','session_id':'s','state':'STOPPED','cursor':1,
                    'has_more':False,'capture':{'items':[{'kind':'text','content':'evidence'}],'views':[]}}
            draft=ContextCaptureDraft();state=RecordingDraft(draft,invoke)
            await state.start({'request':{}},include_view=False)
            await state.stage()
            async def save(): return {'group':{'id':'saved'}}
            with self.assertRaises(RuntimeError): await state.persist(save)
            with self.assertRaises(TaskError): await state.discard()
            self.assertTrue(state.committed)
            self.assertTrue(state.pending)
            self.assertNotIn('discard',operations)
            self.assertEqual(len(draft.entries),1)
        asyncio.run(scenario())

    def test_failure_keeps_buffer_and_retry_saves_once_before_ack(self):
        from taskweave.desktop.context_recording import RecordingDraft
        async def scenario():
            calls=[]
            async def invoke(operation, **options):
                calls.append(operation)
                if operation=='read': return {'recording_id':'r','session_id':'s','state':'STOPPED','cursor':1,'available_after':0,'dropped_count':0,'has_more':False,'capture':{'items':[{'kind':'text','mime_type':'text/plain','content':'actual target','source':'p.record'}],'views':[]}}
                return {'recording_id':'r','session_id':'s','state':'RECORDING' if operation=='start' else 'STOPPED','cursor':1}
            draft=ContextCaptureDraft(); state=RecordingDraft(draft,invoke)
            await state.start({'provider_id':'p','request':{'target_id':'original'}},include_view=False)
            await state.stage()
            self.assertFalse(draft.entries[0]['send_preview'])
            save=AsyncMock(side_effect=[RuntimeError('failed'),{'group':{'id':'saved'}}])
            with self.assertRaises(RuntimeError): await state.persist(save)
            self.assertNotIn('ack',calls)
            self.assertTrue(state.pending)
            await state.persist(save)
            self.assertEqual(calls[-1],'ack')
            self.assertFalse(state.pending)
            self.assertEqual(save.await_count,2)
        asyncio.run(scenario())

    def test_ack_failure_does_not_duplicate_already_committed_group(self):
        from taskweave.desktop.context_recording import RecordingDraft
        async def scenario():
            acks=[0]
            async def invoke(operation,**options):
                if operation=='ack':
                    acks[0]+=1
                    if acks[0]==1: raise RuntimeError('connection lost')
                return {'recording_id':'r','session_id':'s','state':'STOPPED','cursor':1,'has_more':False,'capture':{'items':[{'kind':'text','content':'evidence'}],'views':[]}}
            draft=ContextCaptureDraft(); state=RecordingDraft(draft,invoke)
            await state.start({'provider_id':'p','request':{}},include_view=False)
            await state.stage()
            save=AsyncMock(return_value={'group':{'id':'saved'}})
            with self.assertRaises(RuntimeError): await state.persist(save)
            await state.persist(save)
            self.assertEqual(save.await_count,1)
            self.assertEqual(acks[0],2)
        asyncio.run(scenario())

    def test_removed_recording_is_not_acknowledged_as_saved(self):
        from taskweave.desktop.context_recording import RecordingDraft
        async def scenario():
            invoke=AsyncMock(return_value={'recording_id':'r','session_id':'s','state':'STOPPED','cursor':1,'has_more':False,'capture':{'items':[{'kind':'text','content':'evidence'}],'views':[]}})
            draft=ContextCaptureDraft();state=RecordingDraft(draft,invoke)
            await state.start({'provider_id':'p','request':{}},include_view=False);await state.stage()
            draft.remove(draft.entries[0])
            save=AsyncMock()
            with self.assertRaises(TaskError):await state.persist(save)
            save.assert_not_awaited()
            await state.discard()
            self.assertFalse(state.pending)
        asyncio.run(scenario())

    def test_many_batches_generate_preview_only_once(self):
        from taskweave.desktop.context_recording import RecordingDraft
        async def scenario():
            preview_requests=[]
            async def invoke(operation,**options):
                if operation=='read':
                    preview_requests.append(options.get('include_view'))
                    after=options.get('after',0)
                    return {'recording_id':'r','session_id':'s','state':'STOPPED','cursor':after+1,
                        'has_more':after==0,'capture':{'items':[{'kind':'text','content':str(after+1)}],
                        'views':[{'title':'Preview','renderer':'p.image','data':{}}] if options.get('include_view') else []}}
                return {'recording_id':'r','session_id':'s','state':'STOPPED','cursor':2}
            draft=ContextCaptureDraft();state=RecordingDraft(draft,invoke)
            await state.start({'request':{}},include_view=True)
            await state.stage()
            self.assertEqual(sum(preview_requests),1)
            self.assertEqual(len(draft.entries[0]['capture']['items']),3)
            self.assertEqual(len(draft.entries[0]['capture']['views']),1)
        asyncio.run(scenario())
