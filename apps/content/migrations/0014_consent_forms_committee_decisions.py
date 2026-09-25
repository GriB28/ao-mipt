"""Бланки согласия после решений оргкомитета.

Без рекламных рассылок, со сроком действия «до достижения целей
обработки», перечень данных — ровно то, что собирает сайт, адрес —
только регистрации по паспорту. Заменяем только прежнюю заготовку
(в ней «рекламного, информационного характера»); текст, переписанный
в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="рекламного, информационного характера") \
            .update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0013_consent_forms_from_committee_template")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
