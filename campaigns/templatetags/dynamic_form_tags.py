from django import template

register = template.Library()


@register.filter
def getfield(form, key):
    """Return the BoundField for `key`, or empty string if absent."""
    if not form or key not in form.fields:
        return ""
    return form[key]
