"""Bounded PNG/JPEG container validation; no image decoder dependency."""
from .bridge import require
from .capture import validate_png


def image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        validate_png(data)
        return 'png'
    require(data.startswith(b'\xff\xd8'),'WECHAT_QRCODE_INVALID')
    position=2;frame=False;scan=False
    while position<len(data):
        require(data[position]==255,'WECHAT_QRCODE_INVALID');position+=1
        while position<len(data) and data[position]==255:position+=1
        require(position<len(data),'WECHAT_QRCODE_INVALID')
        marker=data[position];position+=1
        if marker==0xd9:
            require(frame and scan and position==len(data),'WECHAT_QRCODE_INVALID')
            return 'jpg'
        require(marker not in (0,0xd8) and not 0xd0<=marker<=0xd7,'WECHAT_QRCODE_INVALID')
        require(position+2<=len(data),'WECHAT_QRCODE_INVALID')
        length=int.from_bytes(data[position:position+2],'big')
        require(length>=2 and position+length<=len(data),'WECHAT_QRCODE_INVALID')
        if marker in (0xc0,0xc1,0xc2):
            require(length>=8 and int.from_bytes(data[position+3:position+5],'big')>0 and int.from_bytes(data[position+5:position+7],'big')>0,'WECHAT_QRCODE_INVALID')
            frame=True
        position+=length
        if marker==0xda:
            require(frame,'WECHAT_QRCODE_INVALID');scan=True
            while position<len(data):
                if data[position]!=255:position+=1;continue
                require(position+1<len(data),'WECHAT_QRCODE_INVALID')
                next_marker=data[position+1]
                if next_marker==0 or 0xd0<=next_marker<=0xd7:position+=2;continue
                break
    require(False,'WECHAT_QRCODE_INVALID')
