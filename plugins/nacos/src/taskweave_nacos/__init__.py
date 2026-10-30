"""TaskWeave Nacos configuration actions."""
import hashlib
import json
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError
from .client import NacosClient
from .json_update import patch_json, parse_json
from .structured_update import update_document, selected_fields


class NacosAction:
    def __init__(self, operation):
        self.operation = operation
        props = {'profile': {'type': 'string', 'minLength': 1}, 'data_id': {'type': 'string', 'minLength': 1}, 'group': {'type': 'string', 'minLength': 1}, 'namespace': {'type': 'string'}}
        required = ['profile', 'data_id']
        if operation == 'namespaces':
            props = {'profile': props['profile']}
            required = ['profile']
        elif operation == 'select_fields':
            props['format'] = {'enum': ['json', 'yaml']}
            props['paths'] = {'type': 'array', 'minItems': 1, 'items': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'minLength': 1}}}
            required.extend(['format', 'paths'])
        elif operation == 'update_many':
            props.pop('namespace')
            props['namespaces'] = {'type': 'array', 'minItems': 1, 'maxItems': 50, 'uniqueItems': True, 'items': {'type': 'string'}}
            props['format'] = {'enum': ['json', 'yaml']}
            props['operations'] = {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {'op': {'enum': ['set', 'remove', 'list_add', 'list_remove', 'csv_add', 'csv_remove']}, 'path': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'minLength': 1}}, 'value': {}}, 'required': ['op', 'path'], 'additionalProperties': False}}
            required.extend(['format', 'operations', 'namespaces'])
        elif operation == 'update_fields':
            props['format'] = {'enum': ['json', 'yaml']}
            props['operations'] = {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {'op': {'enum': ['set', 'remove', 'list_add', 'list_remove', 'csv_add', 'csv_remove']}, 'path': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'minLength': 1}}, 'value': {}}, 'required': ['op', 'path'], 'additionalProperties': False}}
            required.extend(['format', 'operations'])
        elif operation == 'patch_json':
            props['patch'] = {'type': 'object'}; required.append('patch')
        elif operation == 'publish':
            props['content'] = {'type': 'string', 'minLength': 1}; props['type'] = {'type': 'string', 'minLength': 1}; required.extend(['content', 'type'])
        elif operation == 'list':
            props.pop('data_id'); required.remove('data_id')
            props.update({'data_id': {'type': 'string'}, 'page': {'type': 'integer', 'minimum': 1}, 'page_size': {'type': 'integer', 'minimum': 1, 'maximum': 100}})
        read = operation in ('get', 'get_json', 'list', 'namespaces', 'select_fields')
        identity = {'data_id': {'type': 'string'}, 'group': {'type': 'string'}}
        if operation == 'update_many':
            output = {'type': 'object', 'properties': {'published': {'type': 'array', 'items': {'type': 'object', 'properties': {'namespace': {'type': 'string'}}, 'required': ['namespace'], 'additionalProperties': False}}}, 'required': ['published'], 'additionalProperties': False}
        elif operation == 'select_fields':
            output = {'type': 'object', 'properties': {'operations': {'type': 'array', 'items': {'type': 'object'}}}, 'required': ['operations'], 'additionalProperties': False}
        elif operation == 'namespaces':
            output = {'type': 'object', 'properties': {'namespaces': {'type': 'array', 'items': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}}, 'required': ['id', 'name'], 'additionalProperties': False}}}, 'required': ['namespaces'], 'additionalProperties': False}
        elif operation in ('get', 'get_json'):
            field = 'content' if operation == 'get' else 'value'
            output = {'type': 'object', 'properties': {**identity, field: {'type': 'string' if operation == 'get' else 'object'}}, 'required': ['data_id', 'group', field], 'additionalProperties': False}
        elif operation in ('publish', 'patch_json', 'update_fields', 'delete'):
            field = 'deleted' if operation == 'delete' else 'published'
            output = {'type': 'object', 'properties': {**identity, field: {'type': 'boolean'}}, 'required': ['data_id', 'group', field], 'additionalProperties': False}
        else:
            output = {'type': 'object', 'properties': {'pageItems': {'type': 'array'}}, 'required': ['pageItems']}
        self.spec = CapabilitySpec('nacos.' + operation, {'update_many': '对多个命名空间逐个安全发布字段操作', 'select_fields': '读取所选字段并生成可发布的操作', 'namespaces': '列出可见的 Nacos 命名空间', 'get': '读取 Nacos 配置', 'get_json': '读取 JSON 配置并返回对象', 'list': '查询 Nacos 配置列表', 'publish': '发布完整 Nacos 配置', 'patch_json': '原子校验并增量更新 JSON 配置', 'update_fields': '按字段更新 JSON 或 YAML 配置', 'delete': '删除 Nacos 配置'}[operation],
            {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False},
            output, 'READ' if read else 'WRITE', timeout_ms=3600000 if operation == 'update_many' else 65000, retry_safe=read)

    async def preflight(self, ctx, inputs):
        NacosClient(ctx, inputs['profile'])
        return []

    async def execute(self, ctx, inputs):
        client = NacosClient(ctx, inputs['profile'])
        if self.operation == 'update_many':
            namespaces = inputs.get('namespaces')
            if not isinstance(namespaces, list) or not 1 <= len(namespaces) <= 50 or any(not isinstance(item, str) for item in namespaces) or len(set(namespaces)) != len(namespaces):
                raise PluginError('NACOS_NAMESPACE_INVALID', '目标命名空间须为 1–50 个不重复的 ID')
            completed = []
            for namespace in namespaces:
                ctx.log('INFO', 'Nacos 开始处理命名空间：' + json.dumps(namespace, ensure_ascii=False))
                try:
                    await NacosAction('update_fields').execute(ctx, {**{k: v for k, v in inputs.items() if k != 'namespaces'}, 'namespace': namespace})
                except PluginError as error:
                    raise PluginError('NACOS_BATCH_INCOMPLETE', '批量发布未完成；已成功：' + json.dumps(completed, ensure_ascii=False) + '；当前目标：' + json.dumps(namespace, ensure_ascii=False) + '；错误码：' + error.code + '。请核对当前目标后决定如何继续') from None
                completed.append(namespace)
                ctx.log('INFO', 'Nacos 已发布命名空间：' + json.dumps(namespace, ensure_ascii=False))
            return {'published': [{'namespace': namespace} for namespace in completed]}
        if self.operation == 'namespaces':
            try:
                response = json.loads(await client.request('GET', '/v2/console/namespace/list'))
                if response.get('code') != 0 or not isinstance(response.get('data'), list):
                    raise ValueError()
                namespaces = [{'id': item['namespace'], 'name': item['namespaceShowName']} for item in response['data']]
                if any(not isinstance(item['id'], str) or not isinstance(item['name'], str) for item in namespaces):
                    raise ValueError()
                return {'namespaces': namespaces}
            except (TypeError, ValueError, KeyError, AttributeError):
                raise PluginError('NACOS_RESPONSE_INVALID', '命名空间列表响应无效') from None
        key = {'dataId': inputs.get('data_id', ''), 'group': inputs.get('group', 'DEFAULT_GROUP'), 'tenant': inputs.get('namespace', client.namespace)}
        if self.operation == 'list':
            params = {**key, 'search': 'blur', 'pageNo': inputs.get('page', 1), 'pageSize': inputs.get('page_size', 20)}
            try:
                value = json.loads(await client.request('GET', '/v1/cs/configs', params=params))
            except (ValueError, TypeError):
                raise PluginError('NACOS_RESPONSE_INVALID') from None
            if not isinstance(value, dict) or not isinstance(value.get('pageItems'), list):
                raise PluginError('NACOS_RESPONSE_INVALID')
            return value
        if self.operation == 'select_fields':
            content = await client.request('GET', '/v1/cs/configs', params=key)
            return {'operations': selected_fields(content, inputs['format'], inputs['paths'])}
        if self.operation in ('get', 'get_json'):
            content = await client.request('GET', '/v1/cs/configs', params=key)
            if self.operation == 'get_json':
                return {'data_id': key['dataId'], 'group': key['group'], 'value': parse_json(content)}
            return {'data_id': key['dataId'], 'group': key['group'], 'content': content}
        if self.operation == 'publish' and (not isinstance(inputs.get('type'), str) or not inputs['type']):
            raise PluginError('NACOS_TYPE_REQUIRED', '完整发布时必须指定配置类型')
        if self.operation == 'delete':
            result = await client.request('DELETE', '/v1/cs/configs', params=key)
            if result.strip() == 'false':
                raise PluginError('NACOS_DELETE_REJECTED', 'Nacos 拒绝删除配置')
            if result.strip() != 'true':
                raise PluginError('NACOS_WRITE_UNKNOWN', '删除响应无效，结果未知；请核对目标配置')
            return {'deleted': True, 'data_id': key['dataId'], 'group': key['group']}
        if self.operation in ('patch_json', 'update_fields'):
            if self.operation == 'update_fields':
                try:
                    details = json.loads(await client.request('GET', '/v1/cs/configs', params={**key, 'show': 'all'}))
                    if not isinstance(details, dict) or not isinstance(details.get('content'), str) or not isinstance(details.get('type'), str) or not details['type']:
                        raise ValueError()
                    if details.get('encryptedDataKey'):
                        raise PluginError('NACOS_ENCRYPTED_CONFIG_UNSUPPORTED', '加密配置不支持字段级更新')
                    original = details['content']
                    metadata = {out: details[src] for src, out in {'type': 'type', 'desc': 'desc', 'use': 'use', 'effect': 'effect', 'schema': 'schema'}.items() if isinstance(details.get(src), str)}
                except (TypeError, ValueError):
                    raise PluginError('NACOS_RESPONSE_INVALID', '配置详情缺少内容或类型，停止更新') from None
                content = update_document(original, inputs['format'], inputs['operations'])
            else:
                original = await client.request('GET', '/v1/cs/configs', params=key)
                content = patch_json(original, inputs['patch'])
                metadata = {'type': 'json'}
            headers = {'casMd5': hashlib.md5(original.encode('utf-8')).hexdigest()}
            data = {**key, 'content': content, **metadata}
        else:
            data = {**key, 'content': inputs['content'], 'type': inputs['type']}
            headers = {}
        result = await client.request('POST', '/v1/cs/configs', data=data, headers=headers)
        if result.strip() == 'false':
            raise PluginError('NACOS_PUBLISH_REJECTED', 'Nacos 拒绝发布，增量更新可能发生并发冲突；请重新读取后检查')
        if result.strip() != 'true':
            raise PluginError('NACOS_WRITE_UNKNOWN', '发布响应无效，结果未知；请核对目标配置')
        return {'published': True, 'data_id': key['dataId'], 'group': key['group']}

    async def verify(self, ctx, inputs, output): return []


class BatchUpdate:
    spec = CapabilitySpec('nacos.update_batch', '将多个配置字段操作发布到多个命名空间',
        {'type': 'object', 'properties': {
            'profile': {'type': 'string', 'minLength': 1},
            'namespaces': {'type': 'array', 'minItems': 1, 'maxItems': 50, 'uniqueItems': True, 'items': {'type': 'string'}},
            'configs': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'type': 'object', 'properties': {
                'data_id': {'type': 'string', 'minLength': 1}, 'group': {'type': 'string', 'minLength': 1},
                'format': {'enum': ['json', 'yaml']}, 'operations': {'type': 'array', 'minItems': 1, 'items': {'type': 'object'}}},
                'required': ['data_id', 'format', 'operations'], 'additionalProperties': False}},
        }, 'required': ['profile', 'namespaces', 'configs'], 'additionalProperties': False},
        {'type': 'object', 'properties': {'published': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'namespace': {'type': 'string'}, 'data_id': {'type': 'string'}, 'group': {'type': 'string'}},
            'required': ['namespace', 'data_id', 'group'], 'additionalProperties': False}}},
         'required': ['published'], 'additionalProperties': False}, 'WRITE', timeout_ms=3600000, retry_safe=False)

    async def preflight(self, ctx, inputs):
        NacosClient(ctx, inputs['profile'])
        return []

    async def execute(self, ctx, inputs):
        namespaces, configs = inputs.get('namespaces'), inputs.get('configs')
        if not isinstance(namespaces, list) or not 1 <= len(namespaces) <= 50 or any(not isinstance(x, str) for x in namespaces) or len(set(namespaces)) != len(namespaces) or not isinstance(configs, list) or not 1 <= len(configs) <= 100:
            raise PluginError('NACOS_BATCH_INVALID', '请选择有效且不重复的命名空间和配置')
        identities = []
        for config in configs:
            if not isinstance(config, dict) or set(config) - {'data_id', 'group', 'format', 'operations'} or not isinstance(config.get('data_id'), str) or not config['data_id'] or config.get('format') not in ('yaml', 'json') or not isinstance(config.get('operations'), list) or not config['operations'] or not isinstance(config.get('group', 'DEFAULT_GROUP'), str) or not config.get('group', 'DEFAULT_GROUP'):
                raise PluginError('NACOS_BATCH_INVALID', '配置操作无效')
            identities.append((config.get('group', 'DEFAULT_GROUP'), config['data_id']))
        if len(set(identities)) != len(identities):
            raise PluginError('NACOS_BATCH_INVALID', '配置重复')
        published = []
        for namespace in namespaces:
            for config in configs:
                target = {'namespace': namespace, 'data_id': config['data_id'], 'group': config.get('group', 'DEFAULT_GROUP')}
                ctx.log('INFO', 'Nacos 开始处理目标：' + json.dumps(target, ensure_ascii=False))
                try:
                    await NacosAction('update_fields').execute(ctx, {'profile': inputs['profile'], 'namespace': namespace, **config})
                except PluginError as error:
                    raise PluginError('NACOS_BATCH_INCOMPLETE', '批量发布未完成；已成功：' + json.dumps(published, ensure_ascii=False) + '；当前目标：' + json.dumps(target, ensure_ascii=False) + '；错误码：' + error.code + '。请核对当前目标后决定如何继续') from None
                published.append(target)
                ctx.log('INFO', 'Nacos 已发布目标：' + json.dumps(target, ensure_ascii=False))
        return {'published': published}

    async def verify(self, ctx, inputs, output): return []


class NacosPlugin:
    def manifest(self):
        return {'id': 'nacos', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1', 'dependencies': {}, 'resource_descriptions': {}, 'config_variables': [{'key': 'nacos_profiles', 'type': 'object', 'required': True, 'description': 'Nacos 环境连接配置，密码使用密钥引用'}]}
    def actions(self): return {**{'nacos.' + name: NacosAction(name) for name in ('get', 'get_json', 'list', 'namespaces', 'select_fields', 'publish', 'patch_json', 'update_fields', 'update_many', 'delete')}, 'nacos.update_batch': BatchUpdate()}
    def tools(self): return {}
    def resource_providers(self): return {}
    def result_handlers(self): return {}
    def authoring(self, selected_ids):
        return AuthoringContribution('Nacos 2.x 配置管理：nacos.namespaces 列出命名空间，nacos.select_fields 从 JSON 或 YAML 读取选定的嵌套字段，nacos.update_fields 或 nacos.update_many 执行字段设置、删除、列表增删和逗号字符串增删；使用完整字段路径并采用 CAS 保护。update_many 按顺序发布目标，失败后停止并报告已经成功的目标。nacos.list、nacos.get、nacos.get_json 读取配置，nacos.publish 发布完整内容，nacos.patch_json 合并 JSON 对象。不同 Nacos 连接通过 nacos_profiles 的 profile 选择，namespace 为命名空间 ID。密钥通过 password_ref 配置。写入失败或超时先核对目标，不自动重试。', constraints={'content_format': 'python-async-v1'})
    async def lint(self, step_document): return []
    async def diagnose(self, error, refs): return []
