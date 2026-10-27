"""Добавление страниц Положения и Регламента олимпиады."""

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.legal_templates import LEGAL_PAGES

    Page = apps.get_model("content", "Page")
    for order, (slug, title, body) in enumerate(LEGAL_PAGES, start=20):
        page = Page.objects.filter(slug=slug).first()
        if page is None:
            Page.objects.create(
                slug=slug,
                title=title,
                body=body,
                show_in_menu=False,
                menu_order=order,
                is_published=True,
            )
        else:
            page.title = title
            page.body = body
            page.is_published = True
            page.save(update_fields=["title", "body", "is_published"])


def backwards(apps, schema_editor):
    Page = apps.get_model("content", "Page")
    Page.objects.filter(slug__in=["statute", "regulations"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0025_alter_news_body"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
