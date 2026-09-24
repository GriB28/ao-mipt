"""Бланк для несовершеннолетних без упоминания опеки: «(подопечного)» убрано.

Заменяем только прежнюю заготовку; текст, переписанный в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    Page.objects.filter(slug="consent-form-minor",
                        body__contains="несовершеннолетнего ребенка (подопечного), сведения") \
        .update(body=CONSENT_FORM_MINOR)


class Migration(migrations.Migration):
    dependencies = [("content", "0015_consent_forms_first_person")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
