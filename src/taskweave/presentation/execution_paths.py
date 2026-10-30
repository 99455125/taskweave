"""Project recorded flow visits onto the frozen flow, without evaluating conditions."""
from collections import defaultdict
from dataclasses import dataclass
import json

from taskweave.core.task_flow import is_linear_flow, conditional_branches
from taskweave.core.validation import TaskError


def _part(value):
    return str(value).replace('~', '~0').replace('/', '~1')


@dataclass
class PathMark:
    reached: int = 0
    completed: int = 0
    skipped: int = 0
    pending: int = 0
    not_entered: int = 0

    def add(self, state, completed=False):
        field = {'taken': 'reached', 'not-entered': 'not_entered'}.get(state, state)
        setattr(self, field, getattr(self, field) + 1)
        self.completed += bool(completed)

    @property
    def state(self):
        if self.reached:
            return 'taken'
        if self.pending:
            return 'pending'
        if self.skipped:
            return 'skipped'
        if self.not_entered:
            return 'not-entered'
        return 'pending'

    def label(self, *, branch=False):
        labels = []
        for count, label in ((self.reached, '命中' if branch else '已到达'),
                             (self.skipped, '未命中'), (self.pending, '尚未判定' if branch else '尚未执行'),
                             (self.not_entered, '未进入')):
            if count:
                labels.append(f'{label} {count} 次')
        return ' · '.join(labels)


class ExecutionPaths:
    """One occurrence per recorded loop round; a selected scope narrows its ancestors only."""
    def __init__(self, flow, run, *, scope=None):
        self.nodes = defaultdict(PathMark)
        self.branches = defaultdict(PathMark)
        self.returns = defaultdict(PathMark)
        self.entries = defaultdict(PathMark)
        self.edges = defaultdict(PathMark)
        self.step_marks = {}
        self.errors = {}
        self.scopes = {}
        self.scope = scope
        self._linear = is_linear_flow(flow)
        self._attempts = defaultdict(list)
        self._step_attempts = defaultdict(list)
        self._visible_attempts = defaultdict(list)
        self._instances = {row['execution_path']: row for row in run.get('flow_instances', [])}
        self._children = defaultdict(set)
        for attempt in run.get('attempts', []):
            if attempt.get('valid'):
                self._step_attempts[attempt['step_id']].append(attempt)
                if attempt.get('execution_path'):
                    self._attempts[attempt['execution_path']].append(attempt)
        paths = set(self._instances) | set(self._attempts)
        cursor = json.loads(run.get('flow_cursor_json') or '{}')
        def frames(current):
            for frame in current.get('frames', []):
                yield frame
                for lane in frame.get('lanes', []):
                    yield from frames(lane)
        self._frames = {frame['path']: frame for frame in frames(cursor)}
        paths.update(self._frames)
        for path in paths:
            parts = path.split('/')
            for index in range(1, len(parts)):
                self._children['/'.join(parts[:index])].add(parts[index])
        self._loop_numbers = {}
        self._root_path = '/' + _part(flow['root']['id'])
        self._walk(flow['root'], self._root_path,
                   finished=run.get('status') == 'SUCCEEDED')

    def attempts(self, step_id):
        return self._visible_attempts[step_id]

    def _record(self, path):
        row = self._instances.get(path)
        frame = self._frames.get(path)
        failure = self._instances.get(path + '/$error')
        if row is None:
            # Active cursor frames prove arrival, but do not imply a branch decision.
            if failure is not None:
                return failure, frame or {}
            return ({**frame, 'status': 'RUNNING'}, frame) if frame is not None else (None, {})
        payload = row.get('payload')
        return ({**row, **failure} if failure is not None else row,
                payload if payload is not None else json.loads(row.get('payload_json') or '{}'))

    def _walk(self, node, path, inherited='pending', *, entered=False, finished=False, rounds=()):
        kind, nid = node['kind'], node['id']
        suppressed = inherited in {'skipped', 'not-entered'}
        row, payload = self._record(path)
        reached, completed = False, False
        if kind == 'sequence':
            children = [self._walk(child, path + '/' + _part(child['id']), inherited, rounds=rounds)
                        for child in node['children']]
            reached = not suppressed and (entered or any(item[0] for item in children))
            completed = not suppressed and (finished or bool(children) and all(item[1] for item in children))
            if path == self._root_path:
                completed = finished and (not children or children[-1][1])
            entry = children[0][0] if children else completed
            self.entries[nid].add(inherited if suppressed else 'taken' if entry else 'pending')
            for index in range(1, len(children)):
                traversed = children[index - 1][1] and children[index][0]
                key = (node['children'][index - 1]['id'], node['children'][index]['id'])
                self.edges[key].add(inherited if suppressed else 'taken' if traversed else 'pending')
        elif kind == 'action':
            attempts = [] if suppressed else self._attempts.get(path, [])
            if not suppressed and not attempts and self._linear:
                attempts = self._step_attempts[node['step_id']]
            self._visible_attempts[node['step_id']].extend(attempts)
            reached = not suppressed and bool(row or attempts)
            completed = reached and (attempts[-1]['status'] == 'SUCCEEDED' if attempts
                                     else row['status'] == 'SUCCEEDED')
        elif kind == 'if':
            reached = not suppressed and row is not None
            completed = reached and row['status'] == 'SUCCEEDED'
            selected = payload.get('selected') if reached else None
            if selected is not None and (not isinstance(selected, list) or
                                         any(not isinstance(identity, str) for identity in selected)):
                raise TaskError('FLOW_INVALID', '分支执行记录必须使用分支标识列表')
            for side, branch in conditional_branches(node):
                state = (inherited if suppressed else 'pending' if selected is None
                         else 'taken' if side in selected else 'skipped')
                done = completed and state == 'taken'
                _, branch_done = self._walk(branch, path + '/' + _part(side) + '/' + _part(branch['id']),
                           state if state != 'taken' else 'pending', entered=state == 'taken',
                           finished=done, rounds=rounds)
                self.branches[branch['id']].add(state, branch_done)
        else:  # foreach / loop
            reached = not suppressed and row is not None
            completed = reached and row['status'] == 'SUCCEEDED'
            indices = sorted(int(part) for part in self._children.get(path, ()) if part.isdigit())
            number = self._loop_numbers.setdefault(nid, len(self._loop_numbers) + 1)
            caption = ('遍历列表' if kind == 'foreach' else '条件循环') + f' {number}'
            if self.scope and self.scope.startswith(path + '/'):
                indices = [i for i in indices if self.scope == f'{path}/{i}' or self.scope.startswith(f'{path}/{i}/')]
            if not indices:
                # A successfully exited loop without a recorded iteration never entered its body.
                state = inherited if suppressed else 'not-entered' if completed else 'pending'
                self._walk(node['body'], path + '/unentered/' + _part(node['body']['id']), state, rounds=rounds)
            for index in indices:
                prefix = f'{path}/{index}'
                labels = (*rounds, f'{caption} · 第 {index + 1} 轮')
                self.scopes[prefix] = ' / '.join(labels)
                iteration, _ = self._record(prefix)
                done = iteration is not None and iteration['status'] == 'SUCCEEDED'
                self._walk(node['body'], prefix + '/' + _part(node['body']['id']), inherited,
                           entered=not suppressed, finished=done, rounds=labels)
            # A return is traversed only once a later round has actually been entered.
            all_indices = [int(part) for part in self._children.get(path, ()) if part.isdigit()]
            returned = not suppressed and any(i > 0 for i in all_indices)
            if self.scope and self.scope.startswith(path + '/'):
                returned = not suppressed and any(index + 1 in all_indices for index in indices)
            self.returns[nid].add('taken' if returned else inherited)
        state = inherited if suppressed else 'taken' if reached else 'pending'
        self.nodes[nid].add(state, completed)
        if not suppressed and kind in {'if', 'foreach', 'loop'} and row is not None and row['status'] == 'FAILED':
            self.errors[nid] = row.get('error_code') or '控制执行失败'
        if kind == 'action':
            self.step_marks[node['step_id']] = self.nodes[nid]
        return reached, completed
