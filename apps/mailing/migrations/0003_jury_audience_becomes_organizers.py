"""
Аудитория «жюри» слилась с «организаторами» — см. accounts.0005.
"""

from django.db import migrations


def merge_audience(apps, schema_editor):
    Newsletter = apps.get_model("mailing", "Newsletter")
    Newsletter.objects.filter(audience="jury").update(audience="organizers")


class Migration(migrations.Migration):
    dependencies = [("mailing", "0002_alter_newsletter_audience")]

    operations = [migrations.RunPython(merge_audience, migrations.RunPython.noop)]
