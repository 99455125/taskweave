"""Optional SSH/SFTP plugin and reusable owned transport sessions."""
from dataclasses import replace
from taskweave.plugins.sdk import AuthoringContribution
from taskweave_process import FileResultHandler, CommandFailureResultHandler
from .actions import DECLARATIONS, FailureEvidence, LIST_INPUT, SshAction, TransferFailureResultHandler
from .context import collect_server
from .paths import SshError
from .transport import CONFIG_KEYS, SshSession, configuration, connect_ssh

__all__=['SshPlugin','SshSession','SshError','connect_ssh']


class ConnectionProvider:
    async def open(self,ctx,role): return await connect_ssh(ctx,configuration(ctx))
    async def close(self,resource): await resource.close()


class SshPlugin:
    def __init__(self): self.evidence=FailureEvidence()
    def manifest(self):
        types={'port':'integer','timeout_seconds':'integer','use_agent':'boolean'}
        return {'id':'ssh','api_version':1,'package_version':'0.1.0','core_requires':'>=0.1,<1','dependencies':{},
                'config_variables':[{'key':'ssh_'+key,'type':types.get(key,'string'),'required':key in ('host','username','remote_root'),
                                     'description':'SSH '+key+'; task parameters override environment'} for key in CONFIG_KEYS],
                'context_requests':{'ssh.server':{**LIST_INPUT, 'x-taskweave-context-form': {'rows': [['$provider', '$session', 'role', {'field': 'path', 'width': 2}], ['max_entries', 'max_output_bytes', '$preview']]}}}}
    def actions(self): return {'ssh.'+name:SshAction(name,self.evidence) for name in DECLARATIONS}
    def tools(self):
        tool=SshAction('list_directory',self.evidence)
        tool.spec=replace(tool.spec,id='ssh.inspect_server',description='Read bounded remote directory information without executing commands')
        return {'ssh.inspect_server':tool}
    def resource_providers(self): return {'ssh.connection':ConnectionProvider()}
    def result_handlers(self):
        return {'ssh.file':FileResultHandler(),'ssh.command_failure':CommandFailureResultHandler(),'ssh.transfer_failure':TransferFailureResultHandler()}
    def authoring(self,selected_ids):
        return AuthoringContribution(
            'Configure ssh_host, ssh_port (22), ssh_username, ssh_remote_root and ssh_known_hosts; known_hosts '
            'defaults to ~/.ssh/known_hosts and is always verified. Password/key passphrase use logical secret refs '
            'ssh_password_ref/ssh_key_passphrase_ref; SSH Agent requires explicit ssh_use_agent=true. '
            'ssh.connection is runtime-owned by role. Never return the connection or credentials in JSON. '
            'ssh.exec requires literal argv, cwd/env are POSIX shell-quoted; ssh.run_script explicitly executes a script. '
            'Both are WRITE, never retry automatically; inspect real exit_code. Env/stdin secrets use env_secret_refs/stdin_secret_ref. '
            'Output defaults to 64 KiB per stream (1 KiB–1 MiB), timeout 60 seconds (1–1800). '
            'Remote root and symlink checks are client checks, not a server sandbox. Remote command cancellation attempts termination '
            'and closes this session; side effects remain UNKNOWN. Command/transfer failures save bounded partial diagnostic evidence '
            'in ssh.command_failure/ssh.transfer_failure without making failed attempts successful. '
            'Complete files default to 16 MiB (up to 64 MiB); logs can truncate with a byte cursor. Upload requires ssh_local_root, '
            'writes an exclusive temporary file, verifies SHA-256 and renames without overwrite by default. '
            'Explicit overwrite uses the server posix-rename extension; unsupported servers fail closed. '
            'ssh.download returns artifact metadata; save using ctx.output("ssh.file", name, artifact) in ctx.result(outputs=...). '
            'File contents are business data and are not automatically redacted. Recursive removal requires recursive=true; deleting the root is forbidden.',
            examples=('''async def run(ctx, inputs):
    result = await ctx.call("ssh.exec", {"argv": ["uname", "-s"]})
    return ctx.result(data=result)''','''async def run(ctx, inputs):
    downloaded = await ctx.call("ssh.download", {"remote_path": inputs["report_path"]})
    return ctx.result(data=downloaded, outputs=[ctx.output("ssh.file", "report", downloaded["artifact"])])'''),
            tool_ids=('ssh.inspect_server',),context_provider_ids=('ssh.server',),constraints={'content_format':'python-async-v1'})
    async def collect_context(self,provider_id,ctx,request,*,include_view=True):
        return await collect_server(provider_id,ctx,request,include_view=include_view)
    async def failure_results(self,ctx,error): return await self.evidence.results(ctx,error)
    async def lint(self,document): return []
    async def diagnose(self,error,refs): return []
