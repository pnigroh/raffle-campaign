from django import template

from campaigns.models import Theme

register = template.Library()


@register.simple_tag(takes_context=True)
def theme_static(context, path):
    """Resolve to /theme-assets/<theme.slug>/<path>.

    Looks up ``theme`` in the rendering context; if missing, falls back to
    the default Theme (the row with ``is_default=True``).
    """
    theme = context.get("theme") or Theme.get_default()
    return f"/theme-assets/{theme.slug}/{path}"
