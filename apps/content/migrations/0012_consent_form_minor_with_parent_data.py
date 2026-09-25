"""Бланк для несовершеннолетних снова с данными представителя из анкеты.

Прошлая редакция оставляла для них пустые строки. Заменяем только её
(узнаём по подсказке под строкой); текст, переписанный в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    Page.objects.filter(
        slug="consent-form-minor",
        body__contains="(фамилия, имя, отчество законного представителя полностью)",
    ).update(body=CONSENT_FORM_MINOR)


class Migration(migrations.Migration):
    dependencies = [("content", "0011_consent_forms_without_parent_data")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
