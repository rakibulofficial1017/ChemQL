
[import math as _chemql_math]
public let PI = 3.141592653589793
public let E = 2.718281828459045
public let TAU = 6.283185307179586
public func sqrt
    return _chemql_math.sqrt(arguments[0])
endfunc
public func cbrt
    return _chemql_math.cbrt(arguments[0])
endfunc
public func abs
    return _chemql_math.fabs(arguments[0])
endfunc
public func floor
    return _chemql_math.floor(arguments[0])
endfunc
public func ceil
    return _chemql_math.ceil(arguments[0])
endfunc
public func factorial
    return _chemql_math.factorial(arguments[0])
endfunc
public func gcd
    return _chemql_math.gcd(*arguments)
endfunc
public func lcm
    return _chemql_math.lcm(*arguments)
endfunc
public func sin
    return _chemql_math.sin(arguments[0])
endfunc
public func cos
    return _chemql_math.cos(arguments[0])
endfunc
public func tan
    return _chemql_math.tan(arguments[0])
endfunc
public func asin
    return _chemql_math.asin(arguments[0])
endfunc
public func acos
    return _chemql_math.acos(arguments[0])
endfunc
public func atan
    return _chemql_math.atan(arguments[0])
endfunc
public func atan2
    return _chemql_math.atan2(arguments[0], arguments[1])
endfunc
public func log
    return _chemql_math.log(arguments[0])
endfunc
public func log10
    return _chemql_math.log10(arguments[0])
endfunc
public func log2
    return _chemql_math.log2(arguments[0])
endfunc
public func exp
    return _chemql_math.exp(arguments[0])
endfunc
public func pow
    return _chemql_math.pow(arguments[0], arguments[1])
endfunc
public func hypot
    return _chemql_math.hypot(*arguments)
endfunc
public func degrees
    return _chemql_math.degrees(arguments[0])
endfunc
public func radians
    return _chemql_math.radians(arguments[0])
endfunc
public func isfinite
    return _chemql_math.isfinite(arguments[0])
endfunc
public func isinf
    return _chemql_math.isinf(arguments[0])
endfunc
public func isnan
    return _chemql_math.isnan(arguments[0])
endfunc
public func isclose
    return _chemql_math.isclose(arguments[0], arguments[1])
endfunc
