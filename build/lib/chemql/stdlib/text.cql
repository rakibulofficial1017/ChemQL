# ChemQL standard library: text
[import re as _chemql_re]
public func upper
    return str(arguments[0]).upper()
endfunc
public func lower
    return str(arguments[0]).lower()
endfunc
public func title
    return str(arguments[0]).title()
endfunc
public func capitalize
    return str(arguments[0]).capitalize()
endfunc
public func casefold
    return str(arguments[0]).casefold()
endfunc
public func strip
    [if len(arguments) > 1]
        return str(arguments[0]).strip(str(arguments[1]))
    [endblock]
    return str(arguments[0]).strip()
endfunc
public func lstrip
    return str(arguments[0]).lstrip()
endfunc
public func rstrip
    return str(arguments[0]).rstrip()
endfunc
public func startswith
    return str(arguments[0]).startswith(str(arguments[1]))
endfunc
public func endswith
    return str(arguments[0]).endswith(str(arguments[1]))
endfunc
public func replace
    return str(arguments[0]).replace(str(arguments[1]), str(arguments[2]))
endfunc
public func split
    [if len(arguments) > 1]
        return str(arguments[0]).split(str(arguments[1]))
    [endblock]
    return str(arguments[0]).split()
endfunc
public func join
    return str(arguments[0]).join([str(x) for x in arguments[1:]])
endfunc
public func count
    return str(arguments[0]).count(str(arguments[1]))
endfunc
public func find
    return str(arguments[0]).find(str(arguments[1]))
endfunc
public func isalpha
    return str(arguments[0]).isalpha()
endfunc
public func isdigit
    return str(arguments[0]).isdigit()
endfunc
public func isalnum
    return str(arguments[0]).isalnum()
endfunc
public func isspace
    return str(arguments[0]).isspace()
endfunc
public func reverse
    return str(arguments[0])[::-1]
endfunc
public func regex_search
    return _chemql_re.search(str(arguments[0]), str(arguments[1])) is not None
endfunc
public func regex_findall
    return _chemql_re.findall(str(arguments[0]), str(arguments[1]))
endfunc
public func regex_replace
    return _chemql_re.sub(str(arguments[0]), str(arguments[1]), str(arguments[2]))
endfunc
