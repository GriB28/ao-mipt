"""Бланки согласия: в перечне данных — «дата и место рождения».

Заменяем только прежнюю заготовку (в ней пункт «дата рождения;»); текст,
переписанный в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="<li>дата рождения;</li>").update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0018_consent_forms_participant_speaks")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
