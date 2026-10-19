"""Plain collection inputs and opaque plugin target/session selection."""
from copy import deepcopy
import json

from taskweave.core.validation import TaskError
from taskweave.presentation.context_collection import context_hidden_parameters, context_view_default, merge_context_request


class TargetSelection:
    def __init__(self, options=None):
        self.options = {'selector_label': '上下文实例', 'parameter_mode_label': '使用插件参数',
                        'auto_select_single': False, 'hide_parameters_when_selected': False, **(options or {})}
        self.targets = {}
        self.session_id = None
        self.selected = ''
        self.auto_selected_id = None
        self.revision = 0
        self.loading = self.error = False
        self.note = ''

    @property
    def uses_parameters(self):
        return self.selected not in self.targets

    def select(self, selected):
        self.selected = selected
        self.auto_selected_id = None

    def begin(self):
        self.revision += 1
        previous = '' if self.selected == self.auto_selected_id else self.selected
        self.auto_selected_id = None
        self.loading, self.error = True, False
        self.targets, self.session_id, self.selected = {}, None, ''
        self.note = '正在读取实例…'
        return self.revision, previous

    def apply(self, revision, previous, result):
        if revision != self.revision:
            return False
        self.targets = {target['target_id']: target for target in result['targets']}
        self.session_id = result['session_id']
        self.selected = previous if previous in self.targets else ''
        if not self.selected and self.options['auto_select_single'] and len(self.targets) == 1:
            self.selected = self.auto_selected_id = next(iter(self.targets))
        self.note = '原实例已不可用，请重新选择。' if previous and previous not in self.targets else ''
        self.loading = False
        return True

    def fail(self, revision, error):
        if revision != self.revision:
            return False
        self.loading, self.error = False, True
        self.note = f'实例读取失败，请刷新重试：{error}'
        return True

    def invalidate(self):
        self.revision += 1

    def selection(self):
        if self.loading or self.error:
            raise TaskError('FORM_INVALID', '请等待实例列表加载完成，或刷新重试')
        target = self.targets.get(self.selected)
        return (dict(target['request']), self.session_id) if target else ({}, None)


class CollectionForm:
    def __init__(self, fields, schemas, *, available=None):
        self.fields, self.schemas = fields, schemas
        self.available = set(schemas if available is None else available)
        self.form_schemas = {}
        self.target = None

    def change(self, name, value):
        self.fields[name] = deepcopy(value)

    def provider_removed(self, retained):
        return retained is not None and retained not in self.available

    def provider_choices(self, retained=None):
        return sorted(self.available | ({retained} if retained else set()))

    def run_choices(self, runs, retained=None, *, initial=''):
        eligible = [run for run in runs if run['status'] in {'PAUSED', 'FAILED', 'SUCCEEDED'}]
        available = {run['run_id'] for run in eligible}
        selected = retained if retained is not None else self.fields.get('run', initial)
        missing_retained = bool(retained and retained not in available)
        if selected not in available and not missing_retained:
            selected = ''
        return eligible, selected, missing_retained

    def configure(self, provider, schema):
        self.form_schemas[provider] = schema
        raw = self.fields.setdefault('forms', {}).setdefault(provider, {})
        for name, spec in schema.get('properties', {}).items():
            value, kind = spec.get('default'), spec.get('type', 'string')
            if 'enum' not in spec:
                if kind == 'boolean': value = bool(value)
                elif kind in {'object', 'array'}: value = '' if value is None else json.dumps(value, ensure_ascii=False)
                elif kind not in {'integer', 'number'}: value = '' if value is None else str(value)
            raw.setdefault(name, deepcopy(value))
        return raw

    def change_input(self, provider, name, value):
        self.fields['forms'][provider][name] = deepcopy(value)

    def values(self, provider, exclude=()):
        schema, values = self.form_schemas[provider], self.fields['forms'][provider]
        result = {}
        for name, spec in schema.get('properties', {}).items():
            if name in exclude: continue
            value, kind = values.get(name), spec.get('type', 'string')
            if name in schema.get('required', []) and value in (None, ''):
                raise TaskError('FORM_INVALID', f'{name} 为必录项')
            if kind in {'object', 'array'}:
                if value in (None, ''): continue
                try: value = json.loads(value)
                except ValueError as exc: raise TaskError('FORM_INVALID', f'{name} 需要有效 JSON') from exc
            elif kind == 'integer' and value is not None:
                if value != int(value): raise TaskError('FORM_INVALID', f'{name} 需要整数')
                value = int(value)
            if value is None or (value == '' and name not in schema.get('required', [])): continue
            result[name] = value
        return result

    def start_options(self, *, environment_id=None, step=False):
        provider = self.fields['provider']
        if provider not in self.available:
            raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE', '当前步骤已移除此插件能力，请恢复后再采集或录制')
        schema = self.schemas.get(provider, {})
        hidden = context_hidden_parameters(schema, self.target is not None and not self.target.uses_parameters)
        target_request, session_id = self.target.selection() if self.target else ({}, None)
        request = merge_context_request(self.values(provider, hidden), json.loads(self.fields.get('advanced') or '{}'), target_request)
        options = {'provider_id': provider, 'request': request, 'expected_session_id': session_id}
        if step:
            options['run_id'] = self.fields.get('run') or None
            if not options['run_id']: options['environment_id'] = environment_id or None
        include_view = bool(self.fields.get('include_view')) if context_view_default(schema) is not None else False
        return options, include_view
