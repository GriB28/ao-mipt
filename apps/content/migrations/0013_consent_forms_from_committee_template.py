"""Бланки согласия — по шаблону оргкомитета.

Данные теперь печатаются в строках над текстом (apps/accounts/consent_pdf.py),
а на страницах остаётся сам текст согласия. Заменяем только прежние
заготовки — в них есть подстановка {{ participant_name }}; текст,
переписанный в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="{{ participant_name }}").update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0012_consent_form_minor_with_parent_data")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
