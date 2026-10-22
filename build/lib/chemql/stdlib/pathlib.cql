# ChemQL standard library: pathlib
[import pathlib as _chemql_pathlib]
public func name
    return _chemql_pathlib.Path(str(arguments[0])).name
endfunc
public func stem
    return _chemql_pathlib.Path(str(arguments[0])).stem
endfunc
public func suffix
    return _chemql_pathlib.Path(str(arguments[0])).suffix
endfunc
public func parent
    return str(_chemql_pathlib.Path(str(arguments[0])).parent)
endfunc
public func join
    return str(_chemql_pathlib.Path(str(arguments[0])).joinpath(*(str(part) for part in arguments[1:])))
endfunc
public func exists
    return _chemql_pathlib.Path(str(arguments[0])).exists()
endfunc
public func is_file
    return _chemql_pathlib.Path(str(arguments[0])).is_file()
endfunc
public func is_dir
    return _chemql_pathlib.Path(str(arguments[0])).is_dir()
endfunc
public func read_text
    [if len(arguments) > 1]
        return _chemql_pathlib.Path(str(arguments[0])).read_text(encoding=str(arguments[1]))
    [endblock]
    return _chemql_pathlib.Path(str(arguments[0])).read_text(encoding="utf-8")
endfunc
public func write_text
    [if len(arguments) > 2]
        return _chemql_pathlib.Path(str(arguments[0])).write_text(str(arguments[1]), encoding=str(arguments[2]))
    [endblock]
    return _chemql_pathlib.Path(str(arguments[0])).write_text(str(arguments[1]), encoding="utf-8")
endfunc
