[import collections as _chemql_collections]
[import itertools as _chemql_itertools]
public func unique
    return list(dict.fromkeys(arguments))
endfunc
public func flatten
    return [item for group in arguments for item in (group if isinstance(group, (list, tuple)) else [group])]
endfunc
public func zip
    return list(zip(*arguments))
endfunc
public func pairwise
    return list(_chemql_itertools.pairwise(arguments))
endfunc
public func frequencies
    return dict(_chemql_collections.Counter(arguments))
endfunc
public func group_count
    return dict(_chemql_collections.Counter(arguments))
endfunc
public func product
    return __import__("math").prod(arguments)
endfunc
public func sorted
    return sorted(arguments)
endfunc
public func reversed
    return list(reversed(arguments))
endfunc
