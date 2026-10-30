"""Version 1 display declarations refer to saved business data, never live actions."""
from taskweave.core.validation import TaskError, pointer

BUILTIN_VIEWS = {
    'core.json': {'type': 'json'},
    'core.table': {'type': 'table'},
    'core.image': {'type': 'image'},
    'core.report': {'type': 'report'},
}


def validate_views(data, views, renderers, outputs=()):
    if not isinstance(views, (list, tuple)):
        raise TaskError('RESULT_VIEW_INVALID', 'views 必须是列表')
    titles = set()
    for view in views:
        if not isinstance(view, dict) or not isinstance(view.get('title'), str) or not view['title'].strip():
            raise TaskError('RESULT_VIEW_INVALID', '展示项需要标题')
        if view['title'] in titles:
            raise TaskError('RESULT_VIEW_INVALID', '展示标题不能重复')
        titles.add(view['title'])
        if view.get('renderer') not in renderers:
            raise TaskError('RESULT_VIEW_INVALID', '展示器不可用')
        if 'output' in view:
            if ('pointer' in view or not isinstance(view['output'], str)
                    or view['output'] not in {item.name for item in outputs}
                    or renderers[view['renderer']].get('type') != 'image'):
                raise TaskError('RESULT_VIEW_INVALID', '图片展示需要本次已声明的文件输出，且不能同时指定 pointer')
            continue
        if not isinstance(view.get('pointer', ''), str):
            raise TaskError('RESULT_VIEW_INVALID', '展示字段必须是 JSON Pointer')
        pointer(data, view.get('pointer', ''))
