# ChemQL standard library: datetime
[import datetime as _chemql_datetime]
public func today
    return _chemql_datetime.date.today().isoformat()
endfunc
public func now
    return _chemql_datetime.datetime.now().isoformat(timespec="seconds")
endfunc
public func utcnow
    return _chemql_datetime.datetime.now(_chemql_datetime.timezone.utc).isoformat(timespec="seconds")
endfunc
public func date
    return _chemql_datetime.date(arguments[0], arguments[1], arguments[2]).isoformat()
endfunc
public func time
    return _chemql_datetime.time(*arguments).isoformat()
endfunc
public func timestamp
    return _chemql_datetime.datetime.fromisoformat(str(arguments[0])).timestamp()
endfunc
public func from_timestamp
    return _chemql_datetime.datetime.fromtimestamp(arguments[0]).isoformat(timespec="seconds")
endfunc
public func weekday
    return _chemql_datetime.date.fromisoformat(str(arguments[0])).weekday()
endfunc
public func date_add_days
    return (_chemql_datetime.date.fromisoformat(str(arguments[0])) + _chemql_datetime.timedelta(days=arguments[1])).isoformat()
endfunc
public func date_difference_days
    return (_chemql_datetime.date.fromisoformat(str(arguments[0])) - _chemql_datetime.date.fromisoformat(str(arguments[1]))).days
endfunc
