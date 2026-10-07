"""Complete bounded PNG reads; no screenshot bytes are silently truncated."""
import base64
import binascii
import hashlib
import struct
import time
from .bridge import require


def validate_png(data):
    require(data[:8]==b'\x89PNG\r\n\x1a\n','WECHAT_SCREENSHOT_INVALID')
    offset=8;first=True;ended=False
    while offset<len(data):
        require(offset+12<=len(data),'WECHAT_SCREENSHOT_INVALID')
        length=struct.unpack('>I',data[offset:offset+4])[0];end=offset+12+length
        require(end<=len(data),'WECHAT_SCREENSHOT_INVALID')
        kind=data[offset+4:offset+8];payload=data[offset+8:end-4]
        require(binascii.crc32(kind+payload)&0xffffffff==struct.unpack('>I',data[end-4:end])[0],'WECHAT_SCREENSHOT_INVALID')
        if first:require(kind==b'IHDR' and length==13,'WECHAT_SCREENSHOT_INVALID');first=False
        if kind==b'IEND':require(length==0 and end==len(data),'WECHAT_SCREENSHOT_INVALID');ended=True
        offset=end
    require(ended,'WECHAT_SCREENSHOT_INVALID')


async def capture_bytes(bridge,*,max_bytes,deadline):
    async def request(method,params):
        remaining=deadline-time.monotonic();require(remaining>0,'WECHAT_RPC_TIMEOUT')
        return (await bridge.request(method,params,timeout_seconds=remaining))['result']
    capture=await request('screenshot',{'max_bytes':max_bytes})
    require(type(capture.get('size_bytes')) is int and 0<capture['size_bytes']<=max_bytes,'WECHAT_SCREENSHOT_LIMIT')
    data=bytearray();offset=0
    try:
        while offset<capture['size_bytes']:
            chunk=await request('screenshot_chunk',{'capture_id':capture['capture_id'],'offset':offset})
            try:raw=base64.b64decode(chunk['data'],validate=True)
            except (ValueError,TypeError,KeyError):require(False,'WECHAT_CAPTURE_INVALID')
            require(chunk.get('offset')==offset and 0<len(raw)<=65536 and chunk.get('next_offset')==offset+len(raw),'WECHAT_CAPTURE_INVALID')
            data.extend(raw);offset+=len(raw);require(offset<=capture['size_bytes'],'WECHAT_CAPTURE_INVALID')
        require(hashlib.sha256(data).hexdigest()==capture.get('sha256'),'WECHAT_CAPTURE_INVALID')
        validate_png(data);return bytes(data)
    finally:
        if not bridge.closed:await bridge.request('screenshot_release',{'capture_id':capture['capture_id']},timeout_seconds=2)
