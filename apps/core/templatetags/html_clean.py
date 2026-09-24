from django import template
from django.utils.safestring import mark_safe

from apps.core.sanitize import clean_html

register = template.Library()


@register.filter(name="clean_html")
def clean_html_filter(value):
    """{{ text|clean_html }} — вывести HTML без скриптов (вместо |safe)."""
    return mark_safe(clean_html(value))
