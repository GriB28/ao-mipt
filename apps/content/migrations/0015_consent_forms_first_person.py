"""Бланки согласия от первого лица и с обязательными по 152-ФЗ частями.

Цель обработки, полный перечень действий, перечень публикуемых данных,
права субъекта. Заменяем только прежнюю заготовку (в ней «бесплатный свободный доступ»);
текст, переписанный в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="бесплатный свободный доступ") \
            .update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0014_consent_forms_committee_decisions")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
