"""Бланки согласия без данных представителя на сайте.

Представитель вписывает свои данные от руки, поэтому подстановки
{{ parent_… }} из бланков убраны. Заменяем только нетронутые заготовки
(в них есть {{ parent_document }}): текст, уже переписанный в админке,
не трогаем — там его поправят руками.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="{{ parent_").update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0010_clean_public_texts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
