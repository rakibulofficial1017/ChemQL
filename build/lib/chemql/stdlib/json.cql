
[import json as _chemql_json]
public func dumps
    return _chemql_json.dumps(arguments[0], ensure_ascii=False)
endfunc
public func dumps_pretty
    return _chemql_json.dumps(arguments[0], ensure_ascii=False, indent=2)
endfunc
public func loads
    return _chemql_json.loads(str(arguments[0]))
endfunc
public func json_type
    return type(_chemql_json.loads(str(arguments[0]))).__name__
endfunc
