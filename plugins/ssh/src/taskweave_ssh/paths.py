"""POSIX remote-root validation; these checks are not a server sandbox."""
import posixpath
import asyncssh
from taskweave_process import ProcessError


class SshError(ProcessError):
    pass


def within(root, path):
    return path == root or path.startswith(root.rstrip('/') + '/')


async def resolve_path(sftp, root, path, *, must_exist):
    if not isinstance(path,str) or not path or '\0' in path:
        raise SshError('SSH_PATH_INVALID')
    candidate=posixpath.normpath(posixpath.join(root,path))
    if not within(root,candidate):
        raise SshError('SSH_PATH_INVALID')
    suffix=[]
    current=candidate
    while True:
        try:
            real=await sftp.realpath(current)
            # realpath implementations may return normalized missing paths;
            # lstat proves the component actually exists.
            await sftp.lstat(current)
            break
        except (asyncssh.SFTPNoSuchFile, asyncssh.SFTPNoSuchPath):
            if must_exist or current == root:
                raise SshError('SSH_PATH_NOT_FOUND') from None
            parent,name=posixpath.split(current)
            suffix.insert(0,name)
            current=parent
    if not within(root,real):
        raise SshError('SSH_PATH_INVALID')
    result=posixpath.join(real,*suffix)
    if not within(root,result):
        raise SshError('SSH_PATH_INVALID')
    return result


async def destination_path(session,path):
    """Validate a final symlink but publish to its name, never its referent."""
    resolved=await session.resolve_path(path,must_exist=False)
    if resolved==session.root: raise SshError('SSH_ROOT_WRITE_DENIED')
    lexical=posixpath.normpath(posixpath.join(session.root,path))
    parent=await session.sftp.realpath(posixpath.dirname(lexical))
    if not within(session.root,parent): raise SshError('SSH_PATH_INVALID')
    return posixpath.join(parent,posixpath.basename(lexical))
