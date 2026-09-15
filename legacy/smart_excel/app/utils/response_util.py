from flask import jsonify

class HttpCode(object):
    ok = 200
    server_error = 500
def rep_result(code, msg, data):
    # {code=200, msg='请求成功', data={}}
    return jsonify(code=code, msg=msg, data=data)
def success(data, msg='处理成功'):
    return rep_result(code=HttpCode.ok, msg=msg, data=data)
def error(msg):
    return rep_result(code=HttpCode.server_error, msg=msg, data=None)