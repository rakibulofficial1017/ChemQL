# ChemQL standard library: random
[import random as _chemql_random]
public func seed
    _chemql_random.seed(arguments[0])
    return None
endfunc
public func random
    return _chemql_random.random()
endfunc
public func randint
    return _chemql_random.randint(arguments[0], arguments[1])
endfunc
public func randrange
    return _chemql_random.randrange(*arguments)
endfunc
public func choice
    return _chemql_random.choice(arguments[0])
endfunc
public func sample
    return _chemql_random.sample(arguments[0], arguments[1])
endfunc
public func shuffle
    values = list(arguments[0])
    _chemql_random.shuffle(values)
    return values
endfunc
public func uniform
    return _chemql_random.uniform(arguments[0], arguments[1])
endfunc
