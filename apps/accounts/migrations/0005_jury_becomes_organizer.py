"""
Роль «жюри» упразднена: решения проверяют организаторы.

Перевод существующих учёток, чтобы после сужения списка ролей в базе
не осталось значения, которого больше нет в choices.
"""

from django.db import migrations


def jury_to_organizer(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="jury").update(role="organizer")


def organizer_to_jury(apps, schema_editor):
    """Откат неточен: обратно поедут и настоящие организаторы тоже,
    поэтому возвращаем только тех, у кого нет площадок."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="organizer", managed_venues__isnull=True).update(role="jury")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_alter_participantprofile_city_and_more")]

    operations = [migrations.RunPython(jury_to_organizer, organizer_to_jury)]
