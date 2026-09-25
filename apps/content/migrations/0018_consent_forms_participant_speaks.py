"""Бланки согласия: говорит участник, представитель присоединяется.

Модель — как в согласованных бланках других вузов: согласие даёт школьник,
законный представитель подтверждает его (если участнику нет 18). В согласии
на распространение назван адрес сайта. Заменяем только прежние заготовки
(в них «на сайте олимпиады) только следующих»); текст, переписанный
в админке, не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_FORM_ADULT, CONSENT_FORM_MINOR

    Page = apps.get_model("content", "Page")
    for slug, body in (("consent-form-minor", CONSENT_FORM_MINOR),
                       ("consent-form-adult", CONSENT_FORM_ADULT)):
        Page.objects.filter(slug=slug, body__contains="на сайте олимпиады) только следующих") \
            .update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0017_consent_forms_child_only")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
