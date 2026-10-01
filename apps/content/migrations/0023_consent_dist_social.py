"""Согласие на распространение: кроме сайта, названы сообщества олимпиады
во ВКонтакте, Telegram и MAX — там тоже публикуются фото и победители.

Заменяем текст страниц consent-dist-* только там, где стоит прежняя
заготовка (ресурс — один сайт): переписанное в админке не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_PAGES

    Page = apps.get_model("content", "Page")
    for slug, _, body in CONSENT_PAGES:
        if slug.startswith("consent-dist-"):
            Page.objects.filter(slug=slug, body__contains="<b>Информационный ресурс,</b>").update(body=body)


class Migration(migrations.Migration):
    dependencies = [("content", "0022_lecture_topics_by_subtopics")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
