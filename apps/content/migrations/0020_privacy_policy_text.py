"""Раньше: своя политика обработки ПД вместо черновика.

Теперь своей политики нет — сайт ведёт на Политику МФТИ (0021), так что
миграция ничего не делает. Оставлена, чтобы не ломать цепочку миграций.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("content", "0019_consent_forms_birth_place")]

    operations = []
