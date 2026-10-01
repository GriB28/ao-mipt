"""Согласия по ответу юриста МФТИ (октябрь 2026).

* Бланк — два документа: согласие на обработку (consent-form-*) и
  отдельное согласие на распространение (consent-dist-*, новые страницы).
* Своей политики нет: /page/privacy/ ведёт на Политику МФТИ, страницу
  снимаем с публикации. Снимаем и /page/consent/ — черновик онлайн-согласия,
  на который ничего не ссылается.

Тексты стр. 1 заменяем только там, где стоит прежняя заготовка (в ней
«до достижения целей обработки»): переписанное в админке не трогаем.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import CONSENT_PAGES

    Page = apps.get_model("content", "Page")
    Page.objects.filter(slug__in=["privacy", "consent"]).update(is_published=False)
    for slug, title, body in CONSENT_PAGES:
        page = Page.objects.filter(slug=slug).first()
        if page is None:
            # Нет и страниц стр. 1 — значит, сайт не настроен setup_site,
            # бланк возьмёт тексты из кода.
            if Page.objects.filter(slug__startswith="consent-form-").exists():
                Page.objects.create(slug=slug, title=title, body=body, is_published=False,
                                    show_in_menu=False, menu_order=95)
        elif "до достижения целей обработки" in page.body:
            page.title, page.body = title, body
            page.save(update_fields=["title", "body"])


class Migration(migrations.Migration):
    dependencies = [("content", "0020_privacy_policy_text")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
