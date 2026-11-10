from django import template

register = template.Library()


@register.filter
def money(value):
    try:
        return f"${int(value):,}"
    except (ValueError, TypeError):
        return "$0"
