# ChemQL standard library: fractions
[import fractions as _chemql_fractions]
public func create
    [if len(arguments) > 1]
        return _chemql_fractions.Fraction(arguments[0], arguments[1])
    [endblock]
    return _chemql_fractions.Fraction(str(arguments[0]))
endfunc
public func add
    return _chemql_fractions.Fraction(arguments[0]) + _chemql_fractions.Fraction(arguments[1])
endfunc
public func subtract
    return _chemql_fractions.Fraction(arguments[0]) - _chemql_fractions.Fraction(arguments[1])
endfunc
public func multiply
    return _chemql_fractions.Fraction(arguments[0]) * _chemql_fractions.Fraction(arguments[1])
endfunc
public func divide
    return _chemql_fractions.Fraction(arguments[0]) / _chemql_fractions.Fraction(arguments[1])
endfunc
public func numerator
    return _chemql_fractions.Fraction(arguments[0]).numerator
endfunc
public func denominator
    return _chemql_fractions.Fraction(arguments[0]).denominator
endfunc
public func to_float
    return float(_chemql_fractions.Fraction(arguments[0]))
endfunc
