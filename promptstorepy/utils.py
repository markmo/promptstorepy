def is_empty(value):
    if isinstance(value, list):
        return len(value) == 0
    if is_object(value):
        return len(value.keys()) == 0
    if isinstance(value, str):
        return value == ''
    return value is None

def is_object(value):
    return value is not None and isinstance(value, (dict, object))

def strip_empty_values(obj):
    def inner(val):
        if isinstance(val, list):
            if len(val):
                arr = [inner(x) for x in val if inner(x) is not None]
                if len(arr):
                    return arr
        elif is_object(val):
            obj = {k: inner(v) for k, v in val.items() if inner(v) is not None}
            if not is_empty(obj):
                return obj
        else:
            if val is not None and val != '':
                return val
        return None

    return inner(obj)

def get_search_type(data_type):
    if data_type in ['String', 'DateTime']:
        return 'TEXT'
    elif data_type == 'Boolean':
        return 'TAG'
    elif data_type in ['Double', 'Long']:
        return 'NUMERIC'
    else:
        return 'TEXT'