"""Readable bounded field choices for an observed JSON result."""


def result_fields(value, limit=64):
    fields = {}
    def visit(item, path, depth):
        if len(fields) >= limit:
            return
        kind = ('null' if item is None else 'boolean' if isinstance(item, bool) else
                'integer' if isinstance(item, int) else 'number' if isinstance(item, float) else
                'object' if isinstance(item, dict) else 'array' if isinstance(item, list) else 'string')
        preview = ('{…}' if isinstance(item, dict) else '[…]' if isinstance(item, list) else str(item))
        fields[path] = {'label': f"{path or '全部结果'} · {preview[:60]}" + ('…' if len(preview)>60 else ''), 'type':kind}
        if depth >= 4:
            return
        children = item.items() if isinstance(item, dict) else enumerate(item) if isinstance(item, list) else []
        for key, child in children:
            visit(child, path+'/'+str(key).replace('~','~0').replace('/','~1'), depth+1)
            if len(fields) >= limit:
                break
    visit(value, '', 0)
    return fields
