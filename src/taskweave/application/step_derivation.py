"""Atomic step copies and reviewed splits, without copying execution history."""
from copy import deepcopy

from taskweave.core.task_flow import conditional_branches
from taskweave.core.validation import TaskError, normalize_step, content_tree


class StepDerivation:
    def __init__(self, steps, tasks, contexts, uow):
        self.steps, self.tasks, self.contexts = steps, tasks, contexts
        self.uow = uow

    @staticmethod
    def _location(node, step_id):
        if node['kind'] == 'sequence':
            for index, child in enumerate(node['children']):
                if child['kind'] == 'action' and child['step_id'] == step_id:
                    return node['id'], index
                found = StepDerivation._location(child, step_id)
                if found:
                    return found
        elif node['kind'] == 'if':
            for _, body in conditional_branches(node):
                found = StepDerivation._location(body, step_id)
                if found:
                    return found
        elif node['kind'] in {'loop', 'foreach'}:
            return StepDerivation._location(node['body'], step_id)

    def _snapshot(self, step_id, expected_hash, context_revisions, expected_step_hash):
        source = self.steps.get(step_id)
        task_id = source['task_id']
        if source['content_hash'] != expected_step_hash:
            raise TaskError('EDIT_CONFLICT', '原步骤已更新，请重新打开操作')
        if self.tasks.definition_hash(task_id) != expected_hash:
            raise TaskError('EDIT_CONFLICT', '任务已更新，请重新打开操作')
        groups = self.contexts.list_step_contexts(step_id)
        revisions = {group['context_id']: group['revision'] for group in groups}
        if revisions != context_revisions:
            raise TaskError('EDIT_CONFLICT', '上下文已更新，请重新选择材料')
        return source, groups, self.tasks.flow(task_id)

    def _copy_material(self, source_id, target_id, groups, selected, *, include_empty=False):
        for group in groups:
            ids = [capture['capture_id'] for capture in group['captures'] if capture['capture_id'] in selected]
            if ids:
                self.contexts.transfer_step_context_captures(source_id, group['context_id'], ids, target_id,
                    mode='copy', expected_revision=group['revision'], target_name=group['name'])
            elif include_empty and not group['captures']:
                self.contexts.create_step_context_group(target_id, group['provider_id'], group['name'], group['context_notes'])

    def copy(self, step_id, expected_hash, context_revisions, expected_step_hash):
        with self.uow.transaction():
            source, groups, flow = self._snapshot(step_id, expected_hash, context_revisions, expected_step_hash)
            parent_id, index = self._location(flow['root'], step_id)
            document = deepcopy(normalize_step(source))
            document['name'] += ' 副本'
            saved = self.steps.insert(source['task_id'], document, parent_id, index + 1, expected_hash)
            selected = {capture['capture_id'] for group in groups for capture in group['captures']}
            self._copy_material(step_id, saved['step_id'], groups, selected, include_empty=True)
            return self.steps.get(saved['step_id'])

    def reuse(self, step_id, target_task_id, parent_id, index, expected_hash,
              expected_step_hash, context_revisions, target_expected_hash, bindings):
        """Copy reviewed bindings and material into an explicit target flow slot."""
        with self.uow.transaction():
            source, groups, _ = self._snapshot(step_id, expected_hash, context_revisions, expected_step_hash)
            if not isinstance(bindings, dict):
                raise TaskError('BINDING_INVALID')
            document = deepcopy(normalize_step(source))
            document['name'] += ' 副本'
            document['bindings'] = deepcopy(bindings)
            saved = self.steps.insert(target_task_id, document, parent_id, index, target_expected_hash)
            # Context material is copied, with fresh identities; execution history is never copied.
            for group in groups:
                target = self.contexts.create_step_context_group(saved['step_id'], group['provider_id'],
                    group['name'], group['context_notes'])
                for summary in group['captures']:
                    capture = self.contexts.get_step_context_capture(group['context_id'], summary['capture_id'], step_id)
                    self.contexts.append_step_context_capture(target['context_id'], capture,
                        request=capture['request'], include_view=capture['include_view'], source_page=capture['source_page'],
                        source_session_id=capture['source_session_id'], label=capture['label'], captured_at=capture['captured_at'],
                        step_id=saved['step_id'])
            return self.steps.get(saved['step_id'])

    @staticmethod
    def _check_retained_outputs(source, first, consumers):
        def declared_paths(schema, root=None, prefix=(), visited=frozenset()):
            if not isinstance(schema, dict):
                return set()
            root = schema if root is None else root
            ref = schema.get('$ref')
            if isinstance(ref, str) and ref.startswith('#/') and ref not in visited:
                resolved = root
                for token in ref[2:].split('/'):
                    if not isinstance(resolved, dict):
                        return set()
                    resolved = resolved.get(token.replace('~1', '/').replace('~0', '~'))
                return declared_paths(resolved, root, prefix, visited | {ref})
            paths = set()
            for name, child in schema.get('properties', {}).items():
                path = (*prefix, name)
                paths.add(path)
                paths.update(declared_paths(child, root, path, visited))
            if isinstance(schema.get('items'), dict):
                paths.update(declared_paths(schema['items'], root, (*prefix, '*'), visited))
            return paths
        removed = declared_paths(source['output_schema']) - declared_paths(first['output_schema'])
        if not removed:
            return
        def walk(value):
            if isinstance(value, dict):
                ref = value.get('ref')
                if (isinstance(ref, dict) and ref.get('source') == 'step'
                        and ref.get('step_id') == source['step_id'] and ref.get('output', 'data') == 'data'):
                    pointer = ref.get('item_pointer', ref.get('pointer', ''))
                    tokens = tuple(token.replace('~1', '/').replace('~0', '~') for token in pointer.split('/')[1:])
                    for removed_path in removed:
                        overlap = min(len(tokens), len(removed_path))
                        if all(a == b or a == '*' and b.isdecimal() for a, b in zip(removed_path[:overlap], tokens[:overlap])):
                            raise TaskError('STEP_OUTPUT_REFERENCED',
                                '原步骤输出「/' + '/'.join(removed_path) + '」仍被引用，请保留该输出或先调整引用')
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(consumers)

    def split(self, step_id, first_document, second_document, first_capture_ids, second_capture_ids,
              expected_hash, context_revisions, expected_step_hash):
        with self.uow.transaction():
            source, groups, flow = self._snapshot(step_id, expected_hash, context_revisions, expected_step_hash)
            available = {capture['capture_id'] for group in groups for capture in group['captures']}
            for selection in (first_capture_ids, second_capture_ids):
                if (not isinstance(selection, list) or any(not isinstance(item, str) for item in selection)
                        or len(set(selection)) != len(selection) or not set(selection) <= available):
                    raise TaskError('CONTEXT_MISMATCH', '所选上下文不属于原步骤')
            first, second = normalize_step(first_document), normalize_step(second_document)
            for document in (first, second):
                content_tree(document['step_content'], document['capabilities'])
            self._check_retained_outputs(source, first, [flow, second, *self.steps.list(source['task_id'])])
            parent_id, index = self._location(flow['root'], step_id)
            self.steps.save(source['task_id'], first, step_id, source['content_hash'])
            saved = self.steps.insert(source['task_id'], second, parent_id, index + 1,
                                      self.tasks.definition_hash(source['task_id']))
            self._copy_material(step_id, saved['step_id'], groups, set(second_capture_ids))
            for group in groups:
                revision = group['revision']
                for capture in group['captures']:
                    if capture['capture_id'] not in first_capture_ids:
                        self.contexts.delete_step_context_capture(group['context_id'], capture['capture_id'],
                            expected_revision=revision, step_id=step_id)
                        revision += 1
            # Recheck the whole definition, including conditions and scoped references.
            self.tasks.save_flow(source['task_id'], self.tasks.flow(source['task_id']),
                                 self.tasks.definition_hash(source['task_id']))
            return self.steps.get(saved['step_id'])
