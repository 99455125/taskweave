"""Small purpose tools shared by MCP and function-calling adapters."""
from copy import deepcopy
import jsonschema
from taskweave.core.validation import TaskError


def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


S = {'type': 'string'}
O = {'type': 'object'}
A = {'type': 'array', 'items': S}
COMMON = {'operation': S, 'params': O, 'request_id': S}
TOOLS = {
    'discover': ('Search task, sequence, plan, environment, plugin, context_provider, capability or operation summaries. Page before requesting detail.',
                 schema({'kind': S, 'query': S, 'cursor': {'type': ['string', 'null']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['kind'])),
    'describe': ('Read selected resource sections, or operation parameters. Use kind=operation before mutations.',
                 schema({'kind': S, 'identity': S, 'sections': A}, ['kind', 'identity'])),
    'author': ('Author definitions using discovered operation contracts. materials freezes authoring context; candidate.validate checks packages. Mutations require unique request_id and current baseline.',
               schema({**COMMON, 'bundle_id': S, 'expected_hash': S}, ['operation', 'params'])),
    'context': ('Read or explicitly capture plugin context. Images are omitted unless include_images=true. Captures may interact with the selected live target.',
                schema({**COMMON, 'include_images': {'type': 'boolean'}}, ['operation', 'params', 'request_id'])),
    'execute': ('Trial, confirm and execute using existing TaskWeave lifecycle. task.run requires current expected_hash. Reuse request_id only for identical retries; UNKNOWN requires reconciliation.',
                schema({**COMMON, 'review_spec_id': S}, ['operation', 'params', 'request_id'])),
    'wait': ('Wait at most 30 seconds for compact persisted run status; no screenshots or polling logs.',
             schema({'identity': S, 'kind': {'enum': ['run', 'sequence']}, 'timeout': {'type': 'number', 'minimum': 0, 'maximum': 30}}, ['identity'])),
    'inspect': ('Inspect run, sequence_run, output, result, events, request, bundle or package. kind=operation_result with identity=read operation and params accesses other discovered read operations. Use pointer and text_offset for large bundle/result/text; images require explicit include_images.',
                schema({'kind': S, 'identity': S, 'sections': A, 'cursor': {'type': ['string', 'null']},
                        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'pointer': S,
                        'step_id': S, 'output': S, 'execution_path': S, 'item_pointer': S, 'loop_node_id': S,
                        'params': O, 'text_offset': {'type': 'integer', 'minimum': 0},
                        'after': {'type': 'integer', 'minimum': 0}, 'include_images': {'type': 'boolean'}}, ['kind', 'identity'])),
    'review': ('Prepare immutable acceptance requirements before execution; read/read_spec inspect results; open shows evidence in the connected workbench. Only a human in the workbench can accept/reject.',
               schema({'action': {'enum': ['prepare', 'read', 'read_spec', 'open']}, 'params': O}, ['action', 'params'])),
}


def tool_definitions():
    return [{'type': 'function', 'name': 'taskweave_' + name, 'description': description,
             'parameters': deepcopy(parameters), 'strict': False} for name, (description, parameters) in TOOLS.items()]


def invoke(client, name, arguments):
    operation = name.removeprefix('taskweave_')
    if name != 'taskweave_' + operation or operation not in TOOLS:
        raise TaskError('AGENT_OPERATION_DENIED')
    try:
        jsonschema.validate(arguments, TOOLS[operation][1])
    except jsonschema.ValidationError as exc:
        raise TaskError('AGENT_ARGUMENT_INVALID', '工具参数不符合约定') from exc
    return client.call('agent.' + operation, arguments)
