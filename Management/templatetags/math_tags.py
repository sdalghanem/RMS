from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()

def _to_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)

@register.filter
def mul(a, b):
    return _to_decimal(a) * _to_decimal(b)

@register.filter
def div(a, b):
    b = _to_decimal(b)
    if b == 0:
        return Decimal(0)
    return _to_decimal(a) / b

@register.filter
def sub(a, b):
    try:
        return float(a) - float(b)
    except (TypeError, ValueError):
        return 0
