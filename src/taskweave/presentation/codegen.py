"""Plain candidate state and guarded application, independent of desktop controls."""
from copy import deepcopy
from difflib import unified_diff
import ast
import io
import tokenize
from taskweave.core.codegen_contracts import codegen_digest
from taskweave.core.validation import TaskError, normalize_step


def insert_fragment(source, fragment, position):
    if type(position) is not int or not 0<=position<=len(source):
        raise TaskError('FORM_INVALID','请在 run 函数内重新定位光标。')
    try:
        existing=ast.parse(source)
        generated=ast.parse(fragment)
    except SyntaxError as exc:
        raise TaskError('FORM_INVALID','请先补全当前代码中的语句。') from exc
    occupied={n.id for n in ast.walk(existing) if isinstance(n,ast.Name)}
    assigned={n.id for n in ast.walk(generated) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    renamed={}
    for name in sorted(assigned):
        if name not in occupied:
            occupied.add(name)
            continue
        index=2
        while f'{name}_{index}' in occupied or f'{name}_{index}' in assigned:index+=1
        renamed[name]=f'{name}_{index}'
        occupied.add(renamed[name])
    if renamed:
        class RenameGenerated(ast.NodeTransformer):
            def visit_Name(self,node):
                if node.id in renamed:node.id=renamed[node.id]
                return node
        fragment=ast.unparse(RenameGenerated().visit(generated))
    line_no=source.count('\n',0,position)+1;statement=line_no;start=None
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in {tokenize.INDENT,tokenize.DEDENT,tokenize.NL,tokenize.COMMENT,tokenize.ENDMARKER}:continue
            if start is None:start=token.start[0]
            if token.type==tokenize.NEWLINE:
                if start<=line_no<=token.end[0]:statement=start;break
                start=None
    except (tokenize.TokenError,IndentationError) as exc:
        raise TaskError('FORM_INVALID','请先补全当前代码中的语句。') from exc
    offset=sum(len(line) for line in source.splitlines(keepends=True)[:statement-1])
    line=source[offset:].split('\n')[0];indent=line[:len(line)-len(line.lstrip(' \t'))]
    if not indent or not source[:offset].strip():
        raise TaskError('FORM_INVALID','请将光标放在 run 函数内需要插入动作的行。')
    return source[:offset]+''.join(indent+part+'\n' for part in fragment.splitlines())+source[offset:]


class LocalGenerationFlow:
    def __init__(self,call,identity):
        self.call,self.identity=call,identity
        self.sources=[];self.selected=None;self.result=None;self.bindings={};self.options={}
        self.busy=False;self.generation_identity=None;self.document_digest=None;self.generation=0

    async def load(self,step_id,document):
        identity=self.identity();self.generation+=1;generation=self.generation
        sources=await self.call('step.codegen.sources',step_id=step_id,document=deepcopy(document))
        if identity!=self.identity() or generation!=self.generation:return False
        previous=next((s for s in self.sources if s['capture_id']==self.selected),None)
        self.sources=sources
        if self.selected not in {s['capture_id'] for s in sources}:
            self.selected=next((s['capture_id'] for s in sources if s.get('complete',True)),
                               next((s['capture_id'] for s in sources),None))
            self.result=None;self.bindings={};self.options={}
        elif previous:
            current=next(s for s in sources if s['capture_id']==self.selected)
            if previous.get('source_digest')!=current.get('source_digest'):
                self.result=None;self.bindings={};self.options={}
        return True

    def select(self,capture_id):
        if self.selected!=capture_id:
            self.generation+=1;self.selected=capture_id;self.result=None;self.bindings={};self.options={}

    def parameters(self,step_id,document):
        source=next((s for s in self.sources if s['capture_id']==self.selected),None)
        if source is None:raise TaskError('CODEGEN_SOURCE_REQUIRED','请先在上下文中录制并保存。')
        return {'step_id':step_id,'document':deepcopy(document),'generator_id':source['generator_id'],
                'context_id':source['context_id'],'capture_id':source['capture_id'],
                'expected_source_digest':source['source_digest'],
                'bindings':deepcopy(self.bindings),'options':deepcopy(self.options)}

    async def generate(self,step_id,document):
        if self.busy:raise TaskError('CODEGEN_BUSY','正在生成，请稍候。')
        identity=self.identity();self.generation+=1;generation=self.generation
        params=self.parameters(step_id,document);self.busy=True
        try:result=await self.call('step.codegen.generate',**params)
        finally:self.busy=False
        if identity!=self.identity() or generation!=self.generation:return False
        self.result=result;self.generation_identity=identity
        self.document_digest=codegen_digest(normalize_step(document))
        return True

    def check(self,document):
        if (not self.result or not self.result.get('applicable') or self.identity()!=self.generation_identity
                or codegen_digest(normalize_step(document))!=self.document_digest):
            raise TaskError('EDIT_CONFLICT','步骤、插件或输入已变化，请重新生成并预览。')

    async def apply(self,step_id,document,mode,position=None):
        self.check(document)
        params=self.parameters(step_id,document)
        result=await self.call('step.codegen.generate',**params)
        self.check(document)
        if result.get('candidate_digest')!=self.result.get('candidate_digest'):
            raise TaskError('EDIT_CONFLICT','生成材料或参数已变化，请重新预览。')
        if mode=='replace':return result['source']
        if mode=='insert':return insert_fragment(document['step_content'],result['body_fragment'],position)
        raise TaskError('FORM_INVALID','未知应用方式。')

    def diff(self,document):
        self.check(document)
        return ''.join(unified_diff(document['step_content'].splitlines(keepends=True),
                                   self.result['source'].splitlines(keepends=True),fromfile='当前代码',tofile='生成候选'))
