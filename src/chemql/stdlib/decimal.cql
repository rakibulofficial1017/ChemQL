# ChemQL standard library: decimal
[import decimal as _chemql_decimal]
public func create
    return _chemql_decimal.Decimal(str(arguments[0]))
endfunc
public func add
    return _chemql_decimal.Decimal(str(arguments[0])) + _chemql_decimal.Decimal(str(arguments[1]))
endfunc
public func subtract
    return _chemql_decimal.Decimal(str(arguments[0])) - _chemql_decimal.Decimal(str(arguments[1]))
endfunc
public func multiply
    return _chemql_decimal.Decimal(str(arguments[0])) * _chemql_decimal.Decimal(str(arguments[1]))
endfunc
public func divide
    return _chemql_decimal.Decimal(str(arguments[0])) / _chemql_decimal.Decimal(str(arguments[1]))
endfunc
public func quantize
    return _chemql_decimal.Decimal(str(arguments[0])).quantize(_chemql_decimal.Decimal(str(arguments[1])))
endfunc
public func to_string
    return str(_chemql_decimal.Decimal(str(arguments[0])))
endfunc
