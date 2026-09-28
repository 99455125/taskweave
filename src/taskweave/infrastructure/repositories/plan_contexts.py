"""Persistence for ordered plan context groups and captures."""

import json
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import now, uid
from taskweave.infrastructure.repositories.plan_helpers import decode_plan, expect_plan_revision


class PlanContextRepository:

    @staticmethod
    def _capture_metadata(db, capture_id, values):
        notes, send = values.get("operation_notes"), values.get("send_preview")
        if notes is not None and not isinstance(notes, str):
            raise TaskError("FORM_INVALID", "操作说明必须是文本")
        if send is not None and type(send) is not bool and not (type(send) is int and send in (0, 1)):
            raise TaskError("FORM_INVALID", "发送预览必须是布尔值")
        db.execute("UPDATE plan_context_captures SET operation_notes=COALESCE(?,operation_notes),send_preview=COALESCE(?,send_preview) WHERE capture_id=?",
                   (notes, None if send is None else int(send), capture_id))

    def __init__(self, store):
        self.store = store

    def get(self, plan_id):
        try:
            return decode_plan(self.store.query("SELECT * FROM plans WHERE plan_id=?", (plan_id,), True))
        except TaskError as exc:
            raise TaskError("PLAN_NOT_FOUND", plan_id) from exc

    def _expect(self, db, plan_id, revision):
        return expect_plan_revision(db, plan_id, revision)

    def copy_contexts(self, db, plan_id, target_id, stamp):
        for context in db.execute('SELECT * FROM plan_contexts WHERE plan_id=? ORDER BY order_index', (plan_id,)):
            copied_context_id = uid()
            db.execute('INSERT INTO plan_contexts(context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)', (copied_context_id, target_id, context['provider_id'], context['name'], context['context_notes'], context['order_index'], stamp, stamp))
            for capture in db.execute('SELECT * FROM plan_context_captures WHERE context_id=? ORDER BY order_index', (context['context_id'],)):
                db.execute('INSERT INTO plan_context_captures(capture_id,context_id,order_index,label,request_json,items_json,views_json,include_view,captured_at,source_page,created_at,updated_at,operation_notes,send_preview) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (uid(), copied_context_id, capture['order_index'], capture['label'], capture['request_json'], capture['items_json'], capture['views_json'], capture['include_view'], capture['captured_at'], capture['source_page'], stamp, stamp, capture['operation_notes'], capture['send_preview']))

    def delete_context(self, plan_id, expected_revision, context_id):
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if not db.execute('DELETE FROM plan_contexts WHERE context_id=? AND plan_id=?', (context_id, plan_id)).rowcount:
                raise TaskError('NOT_FOUND', context_id)
            rows = db.execute('SELECT context_id FROM plan_contexts WHERE plan_id=? ORDER BY order_index', (plan_id,)).fetchall()
            for index, row in enumerate(rows):
                db.execute('UPDATE plan_contexts SET order_index=? WHERE context_id=?', (index, row['context_id']))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (now(), plan_id))
        return self.get(plan_id)

    def update_capture_label(self, plan_id, expected_revision, context_id, capture_id, label, operation_notes=None, send_preview=None):
        if not isinstance(label, str):
            raise TaskError('FORM_INVALID', '采集项标题必须是文本')
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if not db.execute('SELECT 1 FROM plan_context_captures c JOIN plan_contexts g USING(context_id) WHERE c.context_id=? AND c.capture_id=? AND g.plan_id=?', (context_id, capture_id, plan_id)).fetchone():
                raise TaskError('NOT_FOUND', capture_id)
            stamp = now()
            db.execute('UPDATE plan_context_captures SET label=?,updated_at=? WHERE capture_id=?', (label.strip(), stamp, capture_id))
            self._capture_metadata(db, capture_id, {"operation_notes": operation_notes, "send_preview": send_preview})
            db.execute('UPDATE plan_contexts SET updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return self.get(plan_id)

    def append_capture(self, plan_id, expected_revision, context_id, capture, *, request=None, include_view=True, session_id=None, label=''):
        stamp, capture_id = (now(), uid())
        items, views = (capture.get('items', []), capture.get('views', []))
        if not items and (not views):
            raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if not db.execute('SELECT 1 FROM plan_contexts WHERE context_id=? AND plan_id=?', (context_id, plan_id)).fetchone():
                raise TaskError('NOT_FOUND', context_id)
            order = db.execute('SELECT COALESCE(MAX(order_index),-1)+1 FROM plan_context_captures WHERE context_id=?', (context_id,)).fetchone()[0]
            db.execute('INSERT INTO plan_context_captures(capture_id,context_id,order_index,label,request_json,items_json,views_json,include_view,captured_at,source_session_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (capture_id, context_id, order, label, json.dumps(request or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views, ensure_ascii=False), int(include_view), stamp, session_id, stamp, stamp))
            self._capture_metadata(db, capture_id, capture)
            db.execute('UPDATE plan_contexts SET updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return {'plan': self.get(plan_id), 'capture': self.get_capture(context_id, capture_id)}

    def add_context(self, plan_id, expected_revision, provider_id, name, context_notes, session_id, items, request=None, views=None, include_view=True):
        name, context_notes = self._context_metadata(name, context_notes)
        if not items and (not views):
            raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
        stamp, context_id = (now(), uid())
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            order_index = db.execute('SELECT COALESCE(MAX(order_index),-1)+1 FROM plan_contexts WHERE plan_id=?', (plan_id,)).fetchone()[0]
            db.execute('INSERT INTO plan_contexts(context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)', (context_id, plan_id, provider_id, name, context_notes, order_index, stamp, stamp))
            capture_id = uid()
            db.execute('INSERT INTO plan_context_captures(capture_id,context_id,order_index,request_json,items_json,views_json,include_view,captured_at,source_session_id,created_at,updated_at) VALUES(?,?,0,?,?,?,?,?,?,?,?)', (capture_id, context_id, json.dumps(request or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views or [], ensure_ascii=False), int(include_view), stamp, session_id, stamp, stamp))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        context = next((x for x in self.contexts(plan_id) if x['context_id'] == context_id))
        capture = next((x for x in context['captures'] if x['capture_id'] == capture_id))
        return {'plan': self.get(plan_id), 'context': context, 'capture': capture}

    def get_capture(self, context_id, capture_id, plan_id=None):
        sql = 'SELECT c.* FROM plan_context_captures c JOIN plan_contexts g USING(context_id) WHERE c.context_id=? AND c.capture_id=?'
        args = [context_id, capture_id]
        if plan_id is not None:
            sql += ' AND g.plan_id=?'
            args.append(plan_id)
        row = self.store.query(sql, args, True)
        row['items'] = json.loads(row.pop('items_json'))
        row['request'] = json.loads(row.pop('request_json'))
        row['views'] = json.loads(row.pop('views_json'))
        row['include_view'] = bool(row['include_view'])
        return row

    def contexts(self, plan_id):
        self.get(plan_id)
        rows = self.store.query('SELECT context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at FROM plan_contexts WHERE plan_id=? ORDER BY order_index', (plan_id,))
        for row in rows:
            captures = self.store.query('SELECT capture_id,order_index,label,operation_notes,send_preview,(length(views_json) > 2) AS has_preview,captured_at,source_page,source_session_id,created_at FROM plan_context_captures WHERE context_id=? ORDER BY order_index', (row['context_id'],))
            for index, capture in enumerate(captures, 1):
                capture['label'] = capture['label'] or f'采集 {index}'
            row['captures'] = captures
            for key in ('item_json', 'request_json', 'views_json', 'include_view', 'captured_at', 'source_session_id'):
                row.pop(key, None)
        return rows

    @staticmethod
    def _context_metadata(name, context_notes):
        if not isinstance(name, str) or not name.strip():
            raise TaskError('FORM_INVALID', '上下文名称不能为空')
        if not isinstance(context_notes, str):
            raise TaskError('FORM_INVALID', '操作说明必须是文本')
        return (name.strip(), context_notes)

    def replace_capture(self, plan_id, expected_revision, context_id, capture_id, capture, *, request=None, include_view=True, session_id=None):
        items, views = (capture.get('items', []), capture.get('views', []))
        stamp = now()
        if not items and (not views):
            raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if not db.execute('SELECT 1 FROM plan_context_captures c JOIN plan_contexts g USING(context_id) WHERE c.context_id=? AND c.capture_id=? AND g.plan_id=?', (context_id, capture_id, plan_id)).fetchone():
                raise TaskError('NOT_FOUND', capture_id)
            db.execute('UPDATE plan_context_captures SET request_json=?,items_json=?,views_json=?,include_view=?,captured_at=?,source_session_id=?,updated_at=? WHERE capture_id=?', (json.dumps(request or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views, ensure_ascii=False), int(include_view), stamp, session_id, stamp, capture_id))
            db.execute('UPDATE plan_contexts SET updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return self.get(plan_id)

    def context_records(self, plan_id):
        self.get(plan_id)
        groups = self.store.query('SELECT context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at FROM plan_contexts WHERE plan_id=? ORDER BY order_index', (plan_id,))
        for group in groups:
            group['captures'] = []
            for capture in self.store.query('SELECT * FROM plan_context_captures WHERE context_id=? ORDER BY order_index', (group['context_id'],)):
                capture['items'] = json.loads(capture.pop('items_json'))
                capture['items'] = [capture['items']] if isinstance(capture['items'], dict) else capture['items']
                capture['request'] = json.loads(capture.pop('request_json'))
                capture['views'] = json.loads(capture.pop('views_json'))
                capture['include_view'] = bool(capture['include_view'])
                group['captures'].append(capture)
        return groups

    def update_context(self, plan_id, expected_revision, context_id, name, context_notes=''):
        name, context_notes = self._context_metadata(name, context_notes)
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            row = db.execute('SELECT 1 FROM plan_contexts WHERE context_id=? AND plan_id=?', (context_id, plan_id)).fetchone()
            if row is None:
                raise TaskError('NOT_FOUND', context_id)
            stamp = now()
            db.execute('UPDATE plan_contexts SET name=?,context_notes=?,updated_at=? WHERE context_id=?', (name, context_notes, stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return self.get(plan_id)

    def save_context_batch(self, plan_id, expected_revision, context_id, provider_id, name, context_notes, captures):
        """Commit one context editor session and bump the plan revision once."""
        name, context_notes = self._context_metadata(name, context_notes)
        if not isinstance(captures, list):
            raise TaskError('FORM_INVALID', '采集项列表无效')
        if context_id is None and (not captures):
            raise TaskError('CONTEXT_EMPTY', '新上下文组至少需要一项采集内容')
        stamp = now()
        context_id = context_id or uid()
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if context_id and db.execute('SELECT 1 FROM plan_contexts WHERE context_id=? AND plan_id=?', (context_id, plan_id)).fetchone():
                group = db.execute('SELECT provider_id FROM plan_contexts WHERE context_id=?', (context_id,)).fetchone()
                if group['provider_id'] != provider_id:
                    raise TaskError('CONTEXT_PROVIDER_MISMATCH', '已有上下文组不能更换采集器')
                db.execute('UPDATE plan_contexts SET name=?,context_notes=?,updated_at=? WHERE context_id=?', (name, context_notes, stamp, context_id))
            else:
                if context_id is not None and db.execute('SELECT 1 FROM plan_contexts WHERE context_id=?', (context_id,)).fetchone():
                    raise TaskError('NOT_FOUND', context_id)
                order = db.execute('SELECT COALESCE(MAX(order_index),-1)+1 FROM plan_contexts WHERE plan_id=?', (plan_id,)).fetchone()[0]
                db.execute('INSERT INTO plan_contexts(context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)', (context_id, plan_id, provider_id, name, context_notes, order, stamp, stamp))
            old = {row['capture_id'] for row in db.execute('SELECT capture_id FROM plan_context_captures WHERE context_id=?', (context_id,)).fetchall()}
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
                    db.execute('UPDATE plan_context_captures SET label=?,order_index=?,updated_at=? WHERE context_id=? AND capture_id=?', (label.strip(), position, stamp, context_id, capture_id))
                    self._capture_metadata(db, capture_id, entry)
                    continue
                capture = entry.get('capture') or {}
                items, views = (capture.get('items', []), capture.get('views', []))
                if not isinstance(items, list) or not isinstance(views, list) or (not isinstance(entry.get('request') or {}, dict)):
                    raise TaskError('FORM_INVALID', '采集结果格式无效')
                if not items and (not views):
                    raise TaskError('CONTEXT_EMPTY', '插件没有返回上下文内容或预览')
                capture_id = uid()
                db.execute('INSERT INTO plan_context_captures(capture_id,context_id,order_index,label,request_json,items_json,views_json,include_view,captured_at,source_session_id,source_page,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (capture_id, context_id, position, label.strip(), json.dumps(entry.get('request') or {}, ensure_ascii=False), json.dumps(items, ensure_ascii=False), json.dumps(views, ensure_ascii=False), int(entry.get('include_view', True)), entry.get('captured_at') or stamp, entry.get('source_session_id'), entry.get('source_page', 'planning'), stamp, stamp))
                self._capture_metadata(db, capture_id, {**capture, **entry})
            for capture_id in old - retained:
                db.execute('DELETE FROM plan_context_captures WHERE context_id=? AND capture_id=?', (context_id, capture_id))
            db.execute('UPDATE plan_contexts SET updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        group = next((item for item in self.contexts(plan_id) if item['context_id'] == context_id))
        return {'plan': self.get(plan_id), 'group': group}

    def reorder_context(self, plan_id, expected_revision, context_id, direction):
        if direction not in {'up', 'down'}:
            raise TaskError('FORM_INVALID', direction)
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            rows = db.execute('SELECT context_id,order_index FROM plan_contexts WHERE plan_id=? ORDER BY order_index', (plan_id,)).fetchall()
            index = next((i for i, row in enumerate(rows) if row['context_id'] == context_id), None)
            if index is None:
                raise TaskError('NOT_FOUND', context_id)
            other = index - 1 if direction == 'up' else index + 1
            if not 0 <= other < len(rows):
                return self.get(plan_id)
            stamp = now()
            db.execute('UPDATE plan_contexts SET order_index=? WHERE context_id=?', (-1, context_id))
            db.execute('UPDATE plan_contexts SET order_index=? WHERE context_id=?', (rows[index]['order_index'], rows[other]['context_id']))
            db.execute('UPDATE plan_contexts SET order_index=? WHERE context_id=?', (rows[other]['order_index'], context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return self.get(plan_id)

    def replace_context(self, plan_id, expected_revision, context_id, provider_id, name, context_notes, session_id, items, request=None, views=None, include_view=True):
        name, context_notes = self._context_metadata(name, context_notes)
        group = next((item for item in self.contexts(plan_id) if item['context_id'] == context_id), None)
        if group is None:
            raise TaskError('NOT_FOUND', context_id)
        self.update_context(plan_id, expected_revision, context_id, name, context_notes)
        if group['captures']:
            return self.replace_capture(plan_id, self.get(plan_id)['revision'], context_id, group['captures'][0]['capture_id'], {'items': items, 'views': views or []}, request=request, include_view=include_view, session_id=session_id)
        return self.get(plan_id)

    def delete_capture(self, plan_id, expected_revision, context_id, capture_id):
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if not db.execute('DELETE FROM plan_context_captures WHERE context_id=? AND capture_id=? AND EXISTS(SELECT 1 FROM plan_contexts WHERE context_id=? AND plan_id=?)', (context_id, capture_id, context_id, plan_id)).rowcount:
                raise TaskError('NOT_FOUND', capture_id)
            for index, row in enumerate(db.execute('SELECT capture_id FROM plan_context_captures WHERE context_id=? ORDER BY order_index', (context_id,)).fetchall()):
                db.execute('UPDATE plan_context_captures SET order_index=? WHERE capture_id=?', (index, row['capture_id']))
            stamp = now()
            db.execute('UPDATE plan_contexts SET updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return self.get(plan_id)

    def reorder_capture(self, plan_id, expected_revision, context_id, capture_id, direction):
        if direction not in {'up', 'down'}:
            raise TaskError('FORM_INVALID', direction)
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            if not db.execute('SELECT 1 FROM plan_contexts WHERE context_id=? AND plan_id=?', (context_id, plan_id)).fetchone():
                raise TaskError('NOT_FOUND', context_id)
            rows = db.execute('SELECT capture_id,order_index FROM plan_context_captures WHERE context_id=? ORDER BY order_index', (context_id,)).fetchall()
            index = next((i for i, x in enumerate(rows) if x['capture_id'] == capture_id), None)
            if index is None:
                raise TaskError('NOT_FOUND', capture_id)
            other = index + (-1 if direction == 'up' else 1)
            if not 0 <= other < len(rows):
                return self.get(plan_id)
            db.execute('UPDATE plan_context_captures SET order_index=-1 WHERE capture_id=?', (capture_id,))
            db.execute('UPDATE plan_context_captures SET order_index=? WHERE capture_id=?', (rows[index]['order_index'], rows[other]['capture_id']))
            db.execute('UPDATE plan_context_captures SET order_index=? WHERE capture_id=?', (rows[other]['order_index'], capture_id))
            stamp = now()
            db.execute('UPDATE plan_contexts SET updated_at=? WHERE context_id=?', (stamp, context_id))
            db.execute('UPDATE plans SET revision=revision+1,updated_at=? WHERE plan_id=?', (stamp, plan_id))
        return self.get(plan_id)
