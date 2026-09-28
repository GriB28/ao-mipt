"""Страница «Политика обработки персональных данных»: вместо черновика —
политика МФТИ, сокращённая и приведённая к олимпиаде.

Заменяем только прежнюю заготовку (в ней плашка «ЧЕРНОВИК»); текст,
переписанный в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import PRIVACY_POLICY

    Page = apps.get_model("content", "Page")
    Page.objects.filter(slug="privacy", body__contains="ЧЕРНОВИК").update(body=PRIVACY_POLICY)


class Migration(migrations.Migration):
    dependencies = [("content", "0019_consent_forms_birth_place")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
