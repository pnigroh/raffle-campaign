from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def percentage(value, total):
    """Calculate percentage."""
    try:
        if total == 0:
            return 0
        return round((value / total) * 100, 1)
    except (TypeError, ZeroDivisionError):
        return 0


@register.simple_tag
def prize_qty_field_name(prize):
    """Return the form field name for prize quantity."""
    return f"prize_qty_{prize.id}"
