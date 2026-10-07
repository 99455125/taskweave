"""Private v1 native write lease, persistent across workers; no global abort."""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid
from .project import require

NAME='.taskweave-uniapp-native-lease'
MAX_OWNER_BYTES=4096


def native_write_state(root):
    path=Path(root)/NAME
    if not os.path.lexists(path):return {'state':'clear'}
    # Never follow an existing marker/symlink or parse arbitrary user content.
    return {'state':'quarantined','lease_path':str(path),'policy':'unconfirmed-native-write-v1','recovery':'independently_owned_new_root'}


def claim_native_lease(root,attempt):
    require(hasattr(os,'O_DIRECTORY') and hasattr(os,'O_NOFOLLOW'),'UNIAPP_PREPARATION_REQUIRED','Native lease requires secure no-follow directory primitives')
    root=Path(root).resolve(strict=True);path=root/NAME
    token=uuid.uuid4().hex;owner={'format':1,'token':token,'root':str(root),'attempt_id':str(attempt),'pid':os.getpid(),'effect_state':'UNCONFIRMED'};raw=json.dumps(owner,sort_keys=True).encode();require(len(raw)<=MAX_OWNER_BYTES,'UNIAPP_NATIVE_LEASE_INVALID')
    try:os.mkdir(path,0o700)
    except FileExistsError:require(False,'UNIAPP_NATIVE_ROOT_QUARANTINED','Native effects may survive in the external host; use an independently owned new project root')
    info=path.lstat();require(stat.S_ISDIR(info.st_mode),'UNIAPP_NATIVE_ROOT_QUARANTINED')
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        opened=os.fstat(descriptor);require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'UNIAPP_NATIVE_LEASE_CHANGED')
        file=os.open('owner.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=descriptor)
        with os.fdopen(file,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        file_info=os.stat('owner.json',dir_fd=descriptor,follow_symlinks=False)
        os.fsync(descriptor)
    finally:os.close(descriptor)
    return {'path':str(path),'directory_identity':(info.st_dev,info.st_ino),'owner_identity':(file_info.st_dev,file_info.st_ino),'owner_sha256':hashlib.sha256(raw).hexdigest()}


def release_confirmed_lease(lease):
    """Only called for a fully verified finite success or proven NOT_STARTED."""
    path=Path(lease['path']);info=path.lstat();require(stat.S_ISDIR(info.st_mode) and (info.st_dev,info.st_ino)==lease['directory_identity'],'UNIAPP_NATIVE_LEASE_CHANGED')
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        opened=os.fstat(descriptor);require((opened.st_dev,opened.st_ino)==lease['directory_identity'] and os.listdir(descriptor)==['owner.json'],'UNIAPP_NATIVE_LEASE_CHANGED')
        file=os.open('owner.json',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=descriptor)
        with os.fdopen(file,'rb') as stream:
            owner=os.fstat(stream.fileno());raw=stream.read(MAX_OWNER_BYTES+1)
        require(stat.S_ISREG(owner.st_mode) and (owner.st_dev,owner.st_ino)==lease['owner_identity'] and len(raw)<=MAX_OWNER_BYTES and hashlib.sha256(raw).hexdigest()==lease['owner_sha256'],'UNIAPP_NATIVE_LEASE_CHANGED')
        current=os.stat('owner.json',dir_fd=descriptor,follow_symlinks=False);require((current.st_dev,current.st_ino)==lease['owner_identity'],'UNIAPP_NATIVE_LEASE_CHANGED')
        os.unlink('owner.json',dir_fd=descriptor);os.fsync(descriptor)
        current=path.lstat();require((current.st_dev,current.st_ino)==lease['directory_identity'],'UNIAPP_NATIVE_LEASE_CHANGED');os.rmdir(path)
    finally:os.close(descriptor)
