"""SQLite persistence for step context groups and ordered captures."""

import json
from taskweave.core.validation import TaskError, dumps
from taskweave.infrastructure.storage import now, uid


class StepContextRepository:
    @staticmethod
    def _capture_metadata(db, capture_id, values):
        notes, send = values.get("operation_notes"), values.get("send_preview")
        if notes is not None and not isinstance(notes, str):
            raise TaskError("FORM_INVALID", "操作说明必须是文本")
        if send is not None and type(send) is not bool and not (type(send) is int and send in (0, 1)):
            raise TaskError("FORM_INVALID", "发送预览必须是布尔值")
        db.execute("UPDATE step_context_captures SET operation_notes=COALESCE(?,operation_notes),send_preview=COALESCE(?,send_preview) WHERE capture_id=?",
                   (notes, None if send is None else int(send), capture_id))

    def __init__(self, store, steps):
        self.store = store
        self.steps = steps

    def query(self, sql, args=(), one=False):
        return self.store.query(sql, args, one)

    def execute(self, sql, args=()):
        return self.store.execute(sql, args)

    def transaction(self):
        return self.store.transaction()

    def step(self, step_id):
        return self.steps.step(step_id)

    @staticmethod
    def _expect_context_revision(db, context_id, expected_revision):
        row = db.execute("SELECT revision FROM step_contexts WHERE context_id=?", (context_id,)).fetchone()
        if row is None:
            raise TaskError("NOT_FOUND", context_id)
        if expected_revision is not None and row["revision"] != expected_revision:
            raise TaskError("EDIT_CONFLICT", f'上下文组已更新：当前版本 {row["revision"]}，请求版本 {expected_revision}')

    def list_step_contexts(self, step_id):
        self.step(step_id)
        rows = self.query('SELECT context_id,step_id,provider_id,name,context_notes,order_index,created_at,updated_at,revision FROM step_contexts WHERE step_id=? ORDER BY order_index', (step_id,))
        for row in rows:
            captures = self.query('SELECT capture_id,order_index,label,operation_notes,send_preview,(length(views_json) > 2) AS has_preview,captured_at,source_page,source_session_id,created_at FROM step_context_captures WHERE context_id=? ORDER BY order_index', (row['context_id'],))
            for index, capture in enumerate(captures, 1):
                capture['label'] = capture['label'] or f'采集 {index}'
            row['captures'] = captures
            for key in ('item_json', 'request_json', 'views_json', 'include_view', 'captured_at', 'source_page'):
                row.pop(key, None)
        return rows

    def get_step_context_capture(self, context_id, capture_id, step_id=None):
        sql = 'SELECT c.*,g.step_id FROM step_context_captures c JOIN step_contexts g USING(context_id) WHERE c.context_id=? AND c.capture_id=?'
        args = [context_id, capture_id]
        if step_id is not None:
            sql += ' AND g.step_id=?'
            args.append(step_id)
        row = self.query(sql, args, True)
        row['items'] = json.loads(row.pop('items_json'))
        if isinstance(row['items'], dict):
            row['items'] = [row['items']]
        row['request'] = json.loads(row.pop('request_json'))
        row['views'] = json.loads(row.pop('views_json'))
        row['include_view'] = bool(row['include_view'])
        return row

    def step_context_records(self, step_id):
        groups = self.query('SELECT context_id,step_id,provider_id,name,context_notes,order_index,created_at,updated_at FROM step_contexts WHERE step_id=? ORDER BY order_index', (step_id,))
        for group in groups:
            group['captures'] = []
            for capture in self.query('SELECT capture_id,order_index,label,operation_notes,send_preview,views_json,request_json,items_json,captured_at,source_page,source_session_id FROM step_context_captures WHERE context_id=? ORDER BY order_index', (group['context_id'],)):
                capture['label'] = capture['label'] or f"采集 {capture['order_index'] + 1}"
                capture['views'] = json.loads(capture.pop('views_json'))
                capture['request'] = json.loads(capture.pop('request_json'))
                capture['items'] = json.loads(capture.pop('items_json'))
                if isinstance(capture['items'], dict):
                    capture['items'] = [capture['items']]
                group['captures'].append(capture)
        return groups

    def create_step_context_group(self, step_id, provider_id, name, context_notes=''):
        step = self.step(step_id)
        if not isinstance(name, str) or not name.strip() or (not isinstance(context_notes, str)):
            raise TaskError('FORM_INVALID', '上下文名称或操作说明无效')
        stamp, context_id = (now(), uid())
        with self.transaction() as db:
            order_index = db.execute('SELECT COALESCE(MAX(order_index),-1)+1 FROM step_contexts WHERE step_id=?', (step_id,)).fetchone()[0]
            db.execute('INSERT INTO step_contexts(context_id,step_id,provider_id,name,context_notes,order_index,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)', (context_id, step_id, provider_id, name.strip(), context_notes, order_index, stamp, stamp))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, step_id))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return next((x for x in self.list_step_contexts(step_id) if x['context_id'] == context_id))

    def save_step_context_batch(self, step_id, context_id, expected_revision, provider_id, name, context_notes, captures):
        """Atomically create/update a context group and its final ordered captures."""
        if not isinstance(name, str) or not name.strip() or (not isinstance(context_notes, str)):
            raise TaskError('FORM_INVALID', '上下文名称或操作说明无效')
        if not isinstance(captures, list):
            raise TaskError('FORM_INVALID', '采集项列表无效')
        if context_id is None and (not captures):
            raise TaskError('CONTEXT_EMPTY', '新上下文组至少需要一项采集内容')
        new_group = context_id is None
        if new_group != (expected_revision is None):
            raise TaskError('EDIT_CONFLICT', '上下文组版本无效，请刷新后重试')
        step = self.step(step_id)
        stamp = now()
        context_id = context_id or uid()
        with self.transaction() as db:
            if expected_revision is None:
                order = db.execute('SELECT COALESCE(MAX(order_index),-1)+1 FROM step_contexts WHERE step_id=?', (step_id,)).fetchone()[0]
                db.execute('INSERT INTO step_contexts(context_id,step_id,provider_id,name,context_notes,order_index,created_at,updated_at,revision) VALUES(?,?,?,?,?,?,?,?,0)', (context_id, step_id, provider_id, name.strip(), context_notes, order, stamp, stamp))
            else:
                group = db.execute('SELECT * FROM step_contexts WHERE context_id=? AND step_id=?', (context_id, step_id)).fetchone()
                if group is None:
                    raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
                self._expect_context_revision(db, context_id, expected_revision)
                if group['provider_id'] != provider_id:
                    raise TaskError('CONTEXT_PROVIDER_MISMATCH', '已有上下文组不能更换采集器')
                db.execute('UPDATE step_contexts SET name=?,context_notes=?,updated_at=? WHERE context_id=?', (name.strip(), context_notes, stamp, context_id))
            old = {row['capture_id']: row for row in db.execute('SELECT capture_id FROM step_context_captures WHERE context_id=?', (context_id,)).fetchall()}
            retained = set()
            for position, entry in enumerate(captures):
                label = entry.get('label', '')
                if not isinstance(label, str):
                    raise TaskError('FORM_INVALID', '采集项标题必须是文本')
                if entry.get('capture_id'):
                    capture_id = entry['capture_id']
                    if capture_id not in old or capture_id in retained:
                        raise TaskError('CONTEXT_MISMATCH', '采集项不属于当前上下文组或重复')
                    retained.add(capture_id)
                    db.execute('UPDATE step_context_captures SET label=?,order_index=?,updated_at=? WHERE context_id=? AND capture_id=?', (label.strip(), position, stamp, context_id, capture_id))
                    self._capture_metadata(db, capture_id, entry)
                    continue
                capture = entry.get('capture') or {}
                items, views = (capture.get('items', []), capture.get('views', []))
                if not isinstance(items, list) or not isinstance(views, list) or (not isinstance(entry.get('request') or {}, dict)):
                    raise TaskError('FORM_INVALID', '采集结果格式无效')
                if not items and (not views):
                    raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
                capture_id = uid()
                db.execute('INSERT INTO step_context_captures(capture_id,context_id,order_index,label,request_json,items_json,views_json,include_view,captured_at,source_session_id,source_page,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (capture_id, context_id, position, label.strip(), json.dumps(entry.get('request') or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views, ensure_ascii=False), int(entry.get('include_view', True)), entry.get('captured_at') or stamp, entry.get('source_session_id'), entry.get('source_page', 'draft'), stamp, stamp))
                self._capture_metadata(db, capture_id, {**capture, **entry})
            for capture_id in set(old) - retained:
                db.execute('DELETE FROM step_context_captures WHERE context_id=? AND capture_id=?', (context_id, capture_id))
            if expected_revision is not None:
                db.execute('UPDATE step_contexts SET revision=revision+1,updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, step_id))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return {'group': next((row for row in self.list_step_contexts(step_id) if row['context_id'] == context_id))}

    def update_step_context_group(self, step_id, context_id, name, context_notes='', expected_revision=None):
        if not isinstance(name, str) or not name.strip() or (not isinstance(context_notes, str)):
            raise TaskError('FORM_INVALID', '上下文名称或操作说明无效')
        step = self.step(step_id)
        stamp = now()
        with self.transaction() as db:
            row = db.execute('SELECT revision FROM step_contexts WHERE context_id=? AND step_id=?', (context_id, step_id)).fetchone()
            if not row:
                raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
            self._expect_context_revision(db, context_id, expected_revision)
            db.execute('UPDATE step_contexts SET name=?,context_notes=?,revision=revision+1,updated_at=? WHERE context_id=?', (name.strip(), context_notes, stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, step_id))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return next((x for x in self.list_step_contexts(step_id) if x['context_id'] == context_id))

    def append_step_context_capture(self, context_id, capture, *, request=None, include_view=True, source_page='draft', source_session_id=None, label='', captured_at=None, expected_revision=None, step_id=None):
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        step = self.step(row['step_id'])
        stamp = now()
        capture_id = uid()
        items = capture.get('items', [])
        views = capture.get('views', [])
        if not items and (not views):
            raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            order = db.execute('SELECT COALESCE(MAX(order_index),-1)+1 FROM step_context_captures WHERE context_id=?', (context_id,)).fetchone()[0]
            db.execute('INSERT INTO step_context_captures(capture_id,context_id,order_index,label,request_json,items_json,views_json,include_view,captured_at,source_session_id,source_page,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (capture_id, context_id, order, label, json.dumps(request or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views, ensure_ascii=False), int(include_view), captured_at or stamp, source_session_id, source_page, stamp, stamp))
            self._capture_metadata(db, capture_id, capture)
            db.execute('UPDATE step_contexts SET revision=revision+1,updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return self.get_step_context_capture(context_id, capture_id)

    def replace_step_context_capture(self, context_id, capture_id, capture, *, request=None, include_view=True, source_page='draft', source_session_id=None, label=None, captured_at=None, expected_revision=None, step_id=None):
        old = self.get_step_context_capture(context_id, capture_id)
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        step = self.step(row['step_id'])
        stamp = now()
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        items, views = (capture.get('items', []), capture.get('views', []))
        if not items and (not views):
            raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            if not db.execute('SELECT 1 FROM step_context_captures WHERE context_id=? AND capture_id=?', (context_id, capture_id)).fetchone():
                raise TaskError('NOT_FOUND', capture_id)
            db.execute('UPDATE step_context_captures SET request_json=?,items_json=?,views_json=?,include_view=?,captured_at=?,source_session_id=?,source_page=?,label=?,updated_at=? WHERE context_id=? AND capture_id=?', (json.dumps(request or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views, ensure_ascii=False), int(include_view), captured_at or stamp, source_session_id, source_page or old['source_page'], old['label'] if label is None else label, stamp, context_id, capture_id))
            db.execute('UPDATE step_contexts SET revision=revision+1,updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return self.get_step_context_capture(context_id, capture_id)

    def delete_step_context_capture(self, context_id, capture_id, expected_revision=None, step_id=None):
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        step = self.step(row['step_id'])
        stamp = now()
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            if not db.execute('DELETE FROM step_context_captures WHERE context_id=? AND capture_id=?', (context_id, capture_id)).rowcount:
                raise TaskError('NOT_FOUND', capture_id)
            for index, item in enumerate(db.execute('SELECT capture_id FROM step_context_captures WHERE context_id=? ORDER BY order_index', (context_id,)).fetchall()):
                db.execute('UPDATE step_context_captures SET order_index=? WHERE capture_id=?', (index, item['capture_id']))
            db.execute('UPDATE step_contexts SET revision=revision+1,updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return {'deleted': capture_id}

    def reorder_step_context_capture(self, context_id, capture_id, direction, expected_revision=None, step_id=None):
        if direction not in {'up', 'down'}:
            raise TaskError('FORM_INVALID', direction)
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        step = self.step(row['step_id'])
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            captures = db.execute('SELECT capture_id,order_index FROM step_context_captures WHERE context_id=? ORDER BY order_index', (context_id,)).fetchall()
            index = next((i for i, item in enumerate(captures) if item['capture_id'] == capture_id), None)
            if index is None:
                raise TaskError('NOT_FOUND', capture_id)
            other = index + (-1 if direction == 'up' else 1)
            if not 0 <= other < len(captures):
                return self.list_step_contexts(row['step_id'])
            stamp = now()
            db.execute('UPDATE step_context_captures SET order_index=-1 WHERE capture_id=?', (capture_id,))
            db.execute('UPDATE step_context_captures SET order_index=? WHERE capture_id=?', (captures[index]['order_index'], captures[other]['capture_id']))
            db.execute('UPDATE step_context_captures SET order_index=?,updated_at=? WHERE capture_id=?', (captures[other]['order_index'], stamp, capture_id))
            db.execute('UPDATE step_contexts SET revision=revision+1,updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return self.list_step_contexts(row['step_id'])

    def update_step_context_capture_label(self, context_id, capture_id, label, expected_revision=None, step_id=None, operation_notes=None, send_preview=None):
        if not isinstance(label, str):
            raise TaskError('FORM_INVALID', '采集项标题必须是文本')
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        step = self.step(row['step_id'])
        stamp = now()
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            if not db.execute('UPDATE step_context_captures SET label=?,updated_at=? WHERE context_id=? AND capture_id=?', (label.strip(), stamp, context_id, capture_id)).rowcount:
                raise TaskError('NOT_FOUND', capture_id)
            self._capture_metadata(db, capture_id, {"operation_notes": operation_notes, "send_preview": send_preview})
            db.execute('UPDATE step_contexts SET revision=revision+1,updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (stamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (stamp, step['task_id']))
        return self.list_step_contexts(row['step_id'])

    def save_step_context(self, step_id, provider_id, name, source_page, item, context_id=None, context_notes='', request=None, views=None, include_view=True, replace_capture=False, captured_at=None, capture_id=None, append=False, expected_revision=None, source_session_id=None):
        if source_page not in {'draft', 'trial_feedback', 'planning_import'}:
            raise TaskError('FORM_INVALID', '上下文来源无效')
        items = item if isinstance(item, list) else [item]
        capture = {'items': items, 'views': views or []}
        if not capture['items'] and (not capture['views']):
            raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
        if context_id is None:
            group = self.create_step_context_group(step_id, provider_id, name, context_notes)
            saved = self.append_step_context_capture(group['context_id'], capture, request=request, include_view=include_view, source_page=source_page, source_session_id=source_session_id, step_id=step_id)
            current = next((row for row in self.list_step_contexts(step_id) if row['context_id'] == group['context_id']))
            return {**current, 'capture': saved, 'item': saved['items'], 'request': saved['request'], 'views': saved['views'], 'include_view': saved['include_view'], 'captured_at': saved['captured_at'], 'source_page': saved['source_page']}
        step = self.step(step_id)
        group_row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        if group_row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        current_group = self.update_step_context_group(step_id, context_id, name, context_notes, expected_revision)
        with self.transaction() as db:
            group = db.execute('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,)).fetchone()
            if group is None or group['step_id'] != step_id:
                raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
            db.execute('UPDATE step_contexts SET provider_id=? WHERE context_id=?', (provider_id, context_id))
        captures = self.query('SELECT capture_id FROM step_context_captures WHERE context_id=? ORDER BY order_index', (context_id,))
        if captures and (replace_capture or capture_id or (not append)):
            selected = capture_id or captures[0]['capture_id']
            saved = self.replace_step_context_capture(context_id, selected, capture, request=request, include_view=include_view, source_page=source_page, source_session_id=source_session_id, expected_revision=current_group['revision'], step_id=step_id)
        else:
            saved = self.append_step_context_capture(context_id, capture, request=request, include_view=include_view, source_page=source_page, source_session_id=source_session_id, expected_revision=current_group['revision'], step_id=step_id)
        group = next((row for row in self.list_step_contexts(step_id) if row['context_id'] == context_id))
        current = next((row for row in self.list_step_contexts(step_id) if row['context_id'] == context_id))
        return {**current, 'capture': saved, 'item': saved['items'], 'request': saved['request'], 'views': saved['views'], 'include_view': saved['include_view'], 'captured_at': saved['captured_at'], 'source_page': saved['source_page']}

    def reorder_step_context(self, context_id, direction, expected_revision=None, step_id=None):
        if direction not in {'up', 'down'}:
            raise TaskError('FORM_INVALID', direction)
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        step = self.step(row['step_id'])
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            rows = db.execute('SELECT context_id,order_index FROM step_contexts WHERE step_id=? ORDER BY order_index', (row['step_id'],)).fetchall()
            index = next((i for i, candidate in enumerate(rows) if candidate['context_id'] == context_id))
            other = index - 1 if direction == 'up' else index + 1
            if not 0 <= other < len(rows):
                return self.list_step_contexts(row['step_id'])
            timestamp = now()
            db.execute('UPDATE step_contexts SET order_index=-1 WHERE context_id=?', (context_id,))
            db.execute('UPDATE step_contexts SET order_index=?,revision=revision+1,updated_at=? WHERE context_id=?', (rows[index]['order_index'], now(), rows[other]['context_id']))
            db.execute('UPDATE step_contexts SET order_index=?,revision=revision+1,updated_at=? WHERE context_id=?', (rows[other]['order_index'], now(), context_id))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (timestamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (timestamp, step['task_id']))
        return self.list_step_contexts(row['step_id'])

    def delete_step_context(self, context_id, expected_revision=None, step_id=None):
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        if step_id is not None and row['step_id'] != step_id:
            raise TaskError('CONTEXT_MISMATCH', '上下文不属于当前步骤')
        step = self.step(row['step_id'])
        timestamp = now()
        with self.transaction() as db:
            self._expect_context_revision(db, context_id, expected_revision)
            db.execute('DELETE FROM step_contexts WHERE context_id=?', (context_id,))
            rows = db.execute('SELECT context_id FROM step_contexts WHERE step_id=? ORDER BY order_index', (row['step_id'],)).fetchall()
            for index, context in enumerate(rows):
                db.execute('UPDATE step_contexts SET order_index=? WHERE context_id=?', (index, context['context_id']))
            db.execute("UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?", (timestamp, row['step_id']))
            db.execute('UPDATE tasks SET updated_at=? WHERE task_id=?', (timestamp, step['task_id']))
        return {'deleted': context_id}
