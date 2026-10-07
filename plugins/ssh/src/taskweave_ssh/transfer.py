"""Bounded complete transfers and exclusive temporary-file publication."""
import asyncio
from contextlib import aclosing
import hashlib
import posixpath
import uuid
import asyncssh
from taskweave_process.artifacts import read_artifact, _stage_bytes, validate_transfer_limit
from .paths import SshError, destination_path
from .transport import _finish


async def owned(awaitable, on_success=None):
    """Receive the reply to a sent SFTP write before cleaning its temporary file."""
    task=asyncio.ensure_future(awaitable)
    try:
        result=await asyncio.shield(task)
    except asyncio.CancelledError:
        result=await _finish(task)
        if on_success is not None: on_success(result)
        raise
    if on_success is not None: on_success(result)
    return result


async def read_bytes(ctx,session,path,max_bytes,*,on_chunk=None):
    validate_transfer_limit(max_bytes)
    resolved=await session.resolve_path(path,must_exist=True)
    attrs=await session.sftp.stat(resolved)
    if attrs.type!=asyncssh.FILEXFER_TYPE_REGULAR:
        raise SshError('SSH_FILE_REQUIRED')
    if attrs.size is not None and attrs.size>max_bytes:
        raise SshError('SSH_TRANSFER_TOO_LARGE')
    data=bytearray()
    async with session.sftp.open(resolved,'rb') as stream:
        while True:
            if ctx.cancelled(): raise SshError('CANCELLED')
            chunk=await stream.read(min(65536,max_bytes+1-len(data)))
            if not chunk: break
            if on_chunk is not None: on_chunk(len(chunk))
            data.extend(chunk)
            if len(data)>max_bytes: raise SshError('SSH_TRANSFER_TOO_LARGE')
    return bytes(data)


async def upload(ctx,session,inputs,progress):
    maximum=inputs.get('max_bytes',16*1024*1024)
    validate_transfer_limit(maximum)
    local_root=session.config.get('local_root')
    if not isinstance(local_root,str) or not local_root:
        raise SshError('SSH_LOCAL_ROOT_REQUIRED')
    _,data=await asyncio.to_thread(read_artifact,local_root,inputs['local_path'],maximum)
    checksum=hashlib.sha256(data).hexdigest()
    if inputs.get('checksum',checksum)!=checksum:
        raise SshError('SSH_CHECKSUM_MISMATCH')
    target=await destination_path(session,inputs['remote_path'])
    if target==session.root: raise SshError('SSH_ROOT_WRITE_DENIED')
    if await session.sftp.lexists(target) and not inputs.get('overwrite',False):
        raise SshError('SSH_TARGET_EXISTS')
    temp=posixpath.join(posixpath.dirname(target),'.taskweave-'+uuid.uuid4().hex)
    try:
        async with session.sftp.open(temp,'xb',encoding=None) as stream:
            for offset in range(0,len(data),32768):
                if ctx.cancelled(): raise SshError('CANCELLED',result=dict(progress),effect_state='UNKNOWN')
                chunk=data[offset:offset+32768]
                def acknowledged(_):
                    progress['bytes_transferred']+=len(chunk)
                await owned(stream.write(chunk),acknowledged)
        remote=await read_bytes(ctx,session,temp,maximum)
        if hashlib.sha256(remote).hexdigest()!=checksum:
            raise SshError('SSH_CHECKSUM_MISMATCH',result=dict(progress),effect_state='UNKNOWN')
        # Ordinary rename (SFTP v3 flags 0) MUST reject an existing destination.
        # posix_rename is only used when explicit overwrite was authorized.
        def published(_):
            progress['completed'].append('published')
            progress['completed_count']+=1
        if inputs.get('overwrite',False):
            await owned(session.sftp.posix_rename(temp,target),published)
        else:
            await owned(session.sftp.rename(temp,target),published)
        return {'path':target,'size_bytes':len(data),'checksum':checksum}
    finally:
        async def clean():
            try: await session.sftp.remove(temp)
            except asyncssh.SFTPNoSuchFile: pass
            except asyncssh.SFTPError:
                # A disconnected peer may have retained the temporary file.
                # Keep original failure and safe progress, never claim cleanup.
                progress['completed'].append('temporary_cleanup_unconfirmed')
        await _finish(asyncio.create_task(clean()))


async def download(ctx,session,inputs,progress):
    def acknowledged(size):
        progress['bytes_transferred']+=size
    data=await read_bytes(ctx,session,inputs['remote_path'],inputs.get('max_bytes',16*1024*1024),on_chunk=acknowledged)
    name=inputs.get('name') or posixpath.basename(inputs['remote_path'])
    artifact=await _stage_bytes(ctx,name,data)
    progress['completed'].append('staged')
    return {'artifact':artifact}


async def remove_tree(ctx,session,path,progress):
    lexical=posixpath.normpath(posixpath.join(session.root,path))
    resolved=await session.resolve_path(path,must_exist=True)
    path=lexical
    if resolved==session.root: raise SshError('SSH_ROOT_REMOVE_DENIED')
    if ctx.cancelled(): raise SshError('CANCELLED',result=dict(progress),effect_state='UNKNOWN')
    attrs=await session.sftp.lstat(path)
    def removed(_):
        progress['completed_count']+=1
        if len(progress['completed'])<100: progress['completed'].append(path)
    if attrs.type==asyncssh.FILEXFER_TYPE_DIRECTORY:
        async with aclosing(session.sftp.scandir(path)) as entries:
            async for item in entries:
                if item.filename not in ('.','..'):
                    await remove_tree(ctx,session,posixpath.join(path,item.filename),progress)
        await owned(session.sftp.rmdir(path),removed)
    else:
        await owned(session.sftp.remove(path),removed)
