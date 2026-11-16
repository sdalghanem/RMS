from decimal import Decimal, InvalidOperation
from django import template
register=template.Library()

@register.filter
def count_display(value):
    try:
        return format(int(value), ',')
    except (TypeError, ValueError, OverflowError):
        return '—'

@register.filter
def money_display(value):
    """Presentation only: fixed decimals and grouping; never writes amounts."""
    try:
        amount=Decimal(str(value))
        return format(amount,',.2f') if amount.is_finite() else '—'
    except (InvalidOperation,TypeError,ValueError):
        return '—'
