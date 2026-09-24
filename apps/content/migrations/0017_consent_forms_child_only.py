"""Бланки согласия: ссылка на закон № 152-ФЗ целиком; только данные ребёнка.

Данные родителя вписываются от руки и на сайте не обрабатываются —
из текста убраны согласие на их обработку и их перечень. Заменяем только
прежние заготовки (в них «статьёй 9»); текст, переписанный в админке,
не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="в соответствии со статьёй 9").update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0016_consent_form_without_guardian")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
