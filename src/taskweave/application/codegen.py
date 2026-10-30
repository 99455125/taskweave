"""Generate candidates from owned persisted captures without touching live resources."""
import ast
from copy import deepcopy
from dataclasses import asdict
import json
from taskweave.core.codegen_contracts import codegen_digest, MAX_RECORDING_BYTES
from taskweave.core.validation import TaskError, normalize_step, content_tree, validate


class CodeGeneration:
    def __init__(self, contexts, steps, registry):
        self.contexts, self.steps, self.registry = contexts, steps, registry

    def _document(self, step_id, document):
        saved=self.steps.step(step_id)
        if not isinstance(document,dict):
            raise TaskError('CODEGEN_DRAFT_INVALID')
        if document.get('step_id',step_id)!=step_id or document.get('task_id',saved['task_id'])!=saved['task_id']:
            raise TaskError('CODEGEN_DRAFT_INVALID')
        doc=normalize_step(deepcopy(document))
        self.registry.check(doc)
        return doc

    def _generator(self, generator_id, doc):
        found=self.registry.code_generators.get(generator_id)
        if found is None or not any(c.startswith(generator_id.split('.')[0]+'.') for c in doc['capabilities']):
            raise TaskError('CODEGEN_UNAVAILABLE','当前步骤未选用支持本地生成的插件。')
        return found

    def _capture(self, step_id, generator_id, context_id, capture_id, doc):
        plugin,spec=self._generator(generator_id,doc)
        groups=self.contexts.list_step_contexts(step_id)
        group=next((g for g in groups if g['context_id']==context_id and g['provider_id'] in spec.provider_ids),None)
        if group is None:
            raise TaskError('CONTEXT_MISMATCH','上下文不属于当前步骤或生成器。')
        capture=self.contexts.get_step_context_capture(context_id,capture_id,step_id)
        # Exclude presentation metadata and screenshot payloads from the converter.
        material={'request':capture['request'],'items':capture['items']}
        if len(json.dumps(material,ensure_ascii=False,allow_nan=False).encode())>MAX_RECORDING_BYTES:
            raise TaskError('CODEGEN_LIMIT','录制材料超过 2MiB。')
        return plugin,spec,capture,material

    def sources(self, step_id, document):
        doc=self._document(step_id,document)
        rows=[]
        for generator_id,(_,spec) in self.registry.code_generators.items():
            if not any(c.startswith(generator_id.split('.')[0]+'.') for c in doc['capabilities']):
                continue
            for group in self.contexts.list_step_contexts(step_id):
                if group['provider_id'] not in spec.provider_ids:
                    continue
                for item in group['captures']:
                    capture=self.contexts.get_step_context_capture(group['context_id'],item['capture_id'],step_id)
                    if not any(i.get('source') in spec.sources for i in capture['items']):
                        continue
                    material={'request':capture['request'],'items':capture['items']}
                    plugin = self.registry.code_generators[generator_id][0]
                    probe = plugin.generate_code(generator_id, deepcopy(material), {}, {})
                    self._validate_result(probe, codegen_digest(material), doc, generator_id)
                    rows.append({'context_id':group['context_id'],'capture_id':item['capture_id'],
                        'generator_id':generator_id,'name':f"{group['name']} · {item['label']}",
                        'generator_name':spec.name,'action_count':probe.get('action_count',0),
                        'complete':all(d.get('code')=='CODEGEN_VALUE_REQUIRED' for d in probe.get('diagnostics',[])),
                        'captured_at':item['captured_at'],'source_digest':codegen_digest(material)})
        return sorted(rows,key=lambda r:r['captured_at'],reverse=True)

    def generate(self, step_id, document, generator_id, context_id, capture_id,
                 expected_source_digest, bindings=None, options=None):
        doc=self._document(step_id,document)
        plugin,spec,_,material=self._capture(step_id,generator_id,context_id,capture_id,doc)
        digest=codegen_digest(material)
        if not isinstance(expected_source_digest,str) or digest!=expected_source_digest:
            raise TaskError('CODEGEN_SOURCE_CHANGED','录制上下文已变化，请重新选择并生成。')
        bindings={} if bindings is None else bindings
        options={} if options is None else options
        if not isinstance(bindings,dict) or not isinstance(options,dict):
            raise TaskError('CODEGEN_BINDING_INVALID')
        validate(options,spec.options_schema)
        schema=doc['input_schema'];properties=schema.get('properties',{})
        names=[v['input'] for v in bindings.values() if isinstance(v,dict) and 'input' in v]
        if 'url_input' in options: names.append(options['url_input'])
        for name in names:
            if not isinstance(name,str) or name not in properties or properties[name].get('type')!='string':
                raise TaskError('CODEGEN_BINDING_INVALID','请选择当前步骤中类型为字符串的已有输入。')
        result=deepcopy(plugin.generate_code(generator_id,deepcopy(material),deepcopy(bindings),deepcopy(options)))
        self._validate_result(result,digest,doc,generator_id)
        # Detect source changes while the pure converter was running.
        _,_,_,current=self._capture(step_id,generator_id,context_id,capture_id,doc)
        if codegen_digest(current)!=digest:
            raise TaskError('CODEGEN_SOURCE_CHANGED','录制上下文已变化，请重新生成。')
        result.update(generator_id=generator_id,context_id=context_id,capture_id=capture_id,
                      draft_digest=codegen_digest(doc),candidate_digest=codegen_digest({
                          'result':result,'draft':doc,'bindings':bindings,'options':options}))
        if doc.get('output_schema'):
            result['warnings']=['生成代码返回输入数据，输出契约需通过调试核对。']
        return result

    def _validate_result(self, result, digest, doc, generator_id):
        if (not isinstance(result,dict) or result.get('result_version')!=1
                or type(result.get('applicable')) is not bool or result.get('source_digest')!=digest
                or not isinstance(result.get('source'),str) or not isinstance(result.get('body_fragment'),str)
                or not isinstance(result.get('diagnostics'),list) or len(result['diagnostics'])>100
                or not isinstance(result.get('input_slots'),list) or len(result['input_slots'])>1000
                or not isinstance(result.get('required_capabilities'),list)
                or len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode())>MAX_RECORDING_BYTES):
            raise TaskError('CODEGEN_RESULT_INVALID')
        for d in result['diagnostics']:
            if not isinstance(d,dict) or not all(isinstance(d.get(k),str) for k in ['code','message','severity']):
                raise TaskError('CODEGEN_RESULT_INVALID')
        for slot in result['input_slots']:
            if (not isinstance(slot,dict) or not isinstance(slot.get('id'),str)
                    or type(slot.get('allow_constant')) is not bool or slot.get('type')!='string'):
                raise TaskError('CODEGEN_RESULT_INVALID')
        required=result['required_capabilities']
        if any(not isinstance(c,str) or not c.startswith(generator_id.split('.')[0]+'.') or c not in self.registry.actions for c in required):
            raise TaskError('CODEGEN_RESULT_INVALID')
        if result['applicable']:
            if any(d['severity']=='error' for d in result['diagnostics']):
                raise TaskError('CODEGEN_RESULT_INVALID')
            if set(required)-set(doc['capabilities']):
                raise TaskError('CAPABILITY_DENIED','当前步骤未授权生成结果所需的全部动作。')
            tree=content_tree(result['source'],doc['capabilities'])
            try:
                fragment=ast.parse(result['body_fragment'])
            except SyntaxError as exc:
                raise TaskError('CODEGEN_RESULT_INVALID') from exc
            body=tree.body[0].body
            if (not body or not isinstance(body[-1],ast.Return)
                    or any(isinstance(n,ast.Return) for n in ast.walk(fragment))
                    or ast.dump(fragment)!=ast.dump(ast.Module(body=body[:-1],type_ignores=[]))):
                raise TaskError('CODEGEN_RESULT_INVALID','插入片段与完整候选不一致。')
            actual=set()
            references=result.get('value_references',{})
            assigned={target.id for assignment in ast.walk(fragment) if isinstance(assignment,ast.Assign)
                      for target in assignment.targets if isinstance(target,ast.Name)}
            if (not isinstance(references,dict) or any(not isinstance(name,str) or name not in assigned
                    or descriptor!={'type':'string'} for name,descriptor in references.items())):
                raise TaskError('CODEGEN_RESULT_INVALID')
            # Validate literal action IDs and inputs. Input references are checked against the draft schema.
            for call in (n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                         and isinstance(n.func.value,ast.Name) and n.func.value.id=='ctx' and n.func.attr=='call'):
                if len(call.args)!=2 or not isinstance(call.args[1],ast.Dict):
                    raise TaskError('CODEGEN_RESULT_INVALID')
                def literal(n):
                    # Generated variables are checked for declaration and shape
                    # here; ctx.call validates their actual values at runtime.
                    if isinstance(n,ast.Name) and n.id in references:
                        return 'generated-runtime-value'
                    if (isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id=='inputs'
                            and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str)
                            and doc['input_schema'].get('properties',{}).get(n.slice.value,{}).get('type')=='string'):
                        return ''
                    if isinstance(n,ast.Dict):return {ast.literal_eval(k):literal(v) for k,v in zip(n.keys,n.values)}
                    return ast.literal_eval(n)
                try:
                    params=literal(call.args[1]);action_id=ast.literal_eval(call.args[0])
                    actual.add(action_id)
                    # Runtime enforces data-specific restrictions; this checks shape and literal constraints.
                    validate(params,self.registry.actions[action_id].spec.input_schema)
                except (ValueError,TypeError,KeyError) as exc:
                    raise TaskError('CODEGEN_RESULT_INVALID') from exc
            if actual != set(required):
                raise TaskError('CODEGEN_RESULT_INVALID')
        elif result['source'] or result['body_fragment']:
            raise TaskError('CODEGEN_RESULT_INVALID')
