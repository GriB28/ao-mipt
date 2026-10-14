"""
Теги и фильтры шаблонов для склонения слов в русском языке.
"""

from django import template
from apps.core.plural import (
    get_model_accusative,
    get_model_plural,
    noun_to_accusative,
    plural_ru,
)

register = template.Library()


@register.filter(name="ru_plural")
def ru_plural_filter(value, forms):
    """
    Выбирает форму склонения слова на основе числительного.
    Формы можно передать через запятую, например:
    "письмо,письма,писем" или "получит,получат,получат"
    """
    if isinstance(forms, str):
        parts = [p.strip() for p in forms.split(",")]
    elif isinstance(forms, (list, tuple)):
        parts = [str(p).strip() for p in forms]
    else:
        return ""

    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return plural_ru(value, parts[0], parts[1], parts[1])
    return plural_ru(value, parts[0], parts[1], parts[2])


@register.filter(name="ru_plural_format")
def ru_plural_format_filter(value, forms):
    """
    Возвращает строку с числом и склонённым словом:
    {{ 6|ru_plural_format:"письмо,письма,писем" }} -> "6 писем"
    """
    word = ru_plural_filter(value, forms)
    return f"{value} {word}".strip()


@register.simple_tag
def ru_model_plural(opts, count):
    """
    Возвращает склонённое название модели для переданного количества.
    Использование: {% ru_model_plural cl.opts cl.result_count %}
    """
    return get_model_plural(opts, count)


@register.simple_tag
def ru_model_plural_format(opts, count):
    """
    Возвращает строку с числом и склонённым названием модели.
    Использование: {% ru_model_plural_format cl.opts cl.result_count %}
    """
    word = get_model_plural(opts, count)
    return f"{count} {word}".strip()


@register.simple_tag
def ru_model_acc(opts):
    """
    Возвращает название модели в винительном падеже (кого? что?):
    {% ru_model_acc cl.opts %} -> "рассылку", "площадку", "пользователя"
    """
    return get_model_accusative(opts)


@register.filter(name="ru_acc")
def ru_acc_filter(value):
    """
    Фильтр для преобразования слова в винительный падеж.
    """
    return noun_to_accusative(str(value))
