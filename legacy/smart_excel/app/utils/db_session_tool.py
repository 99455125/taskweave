import functools

from app.utils.thread_pool import local_storage
from db_server.db_init import db

# 自动注入session
def inject_db_session(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 检查 session 是否在 kwargs 中，或者是否作为位置参数传递
        session = kwargs.get('session')
        session_arg_index = -1

        # 尝试从 func 的参数名中找到 'session' 的位置
        try:
            arg_names = func.__code__.co_varnames[:func.__code__.co_argcount]
            if 'session' in arg_names:
                session_arg_index = arg_names.index('session')
        except AttributeError:
            pass # 如果无法获取参数名，则跳过

        if session_arg_index != -1 and len(args) > session_arg_index:
            # 'session' 是一个位置参数
            if args[session_arg_index] is None:
                # 创建一个新的 args 元组，其中 session 被替换
                args_list = list(args)
                args_list[session_arg_index] = get_session()
                args = tuple(args_list)
            # 如果位置参数已提供且不为 None，则使用它
            # session = args[session_arg_index] # 这行不需要，因为我们直接修改args
        elif 'session' in kwargs and kwargs['session'] is None:
            # 'session' 是一个关键字参数且为 None
            kwargs['session'] = get_session()
        elif 'session' not in kwargs and session_arg_index == -1:
            # 'session' 参数不存在于 args 或 kwargs 中，则添加它
            # 这假设 'session' 是方法定义中的最后一个参数，或者可以作为 kwarg 添加
            # 如果方法签名中没有 session，这可能会导致问题，
            # 但对于 clear_step 来说，它有 session 参数。
            kwargs['session'] = get_session()
        elif session is None and session_arg_index != -1 and len(args) <= session_arg_index :
             # session 是一个关键字参数，但未在调用中提供，且其默认值为 None
             kwargs['session'] = get_session()


        return func(*args, **kwargs)
    return wrapper


def get_session():
    if hasattr(local_storage, 'session') and local_storage.session:
        return local_storage.session
    else:
        return db.session
