"""
Загрузка фотографий финалов из папки.

    python manage.py import_photos albums/

Имя файла задаёт сезон: sez1.png → АО I, sez6.png → АО VI. Файлы
переносятся в media/photos/, в базе остаётся путь к ним.

Команда идемпотентна: повторный запуск не задваивает снимки — фото
опознаётся по имени исходного файла. Если запись в базе есть, а самого
файла в media нет (базу перенесли без загрузок, том пересоздали), файл
кладётся заново.

    python manage.py import_photos albums/ --replace

С --replace уже загруженные снимки заменяются файлами из папки, если те
отличаются: так обновляют фотографии на версии получше.
"""

import re
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.content.models import Photo
from apps.seasons.models import Season

# sez1 → первый сезон, sez6 → шестой. Сезон в базе называется по году
# финала: АО I прошла в 2021-м, значит год = 2020 + номер.
NAME_RE = re.compile(r"sez(?P<number>\d+)", re.IGNORECASE)
FIRST_SEASON_YEAR = 2021

SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class Command(BaseCommand):
    help = "Загружает фотографии финалов из папки в галерею"

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Папка с файлами вида sez1.png")
        parser.add_argument("--caption", default="Финалисты олимпиады",
                            help="Подпись к снимкам")
        parser.add_argument("--replace", action="store_true",
                            help="Заменить уже загруженные снимки файлами из папки")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"Нет такой папки: {folder}")

        created = restored = replaced = skipped = 0
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in SUFFIXES:
                continue

            match = NAME_RE.search(path.stem)
            if not match:
                self.stderr.write(f"  пропущен (не разобрано имя): {path.name}")
                continue

            number = int(match.group("number"))
            season = self._season(number)
            # Опознаём по имени файла: Django при коллизии допишет к нему
            # суффикс, поэтому ищем по началу имени, а не по точному совпадению.
            photo = Photo.objects.filter(image__contains=path.stem, season=season).first()
            if photo:
                content = path.read_bytes()
                missing = not photo.image.storage.exists(photo.image.name)
                if missing or (options["replace"] and self._differs(photo, content)):
                    # Старый файл убираем первым: тогда новый ляжет под тем
                    # же именем, без суффикса.
                    photo.image.delete(save=False)
                    photo.image.save(path.name, ContentFile(content))
                    if missing:
                        restored += 1
                    else:
                        replaced += 1
                    self.stdout.write(f"  {path.name} → {season.title} (файл обновлён)")
                else:
                    skipped += 1
                continue

            Photo.objects.create(
                season=season,
                image=ContentFile(path.read_bytes(), name=path.name),
                caption=options["caption"],
                order=number,
            )
            created += 1
            self.stdout.write(f"  {path.name} → {season.title}")

        self.stdout.write(self.style.SUCCESS(
            f"Добавлено: {created}, восстановлено: {restored}, заменено: {replaced}, "
            f"пропущено как уже загруженные: {skipped}"
        ))

    @staticmethod
    def _differs(photo, content):
        with photo.image.open("rb") as stored:
            return stored.read() != content

    def _season(self, number):
        """Сезон по номеру олимпиады. Недостающий заводим сами."""
        from apps.content.management.commands.import_archive import roman

        year = FIRST_SEASON_YEAR + number - 1
        season, _ = Season.objects.get_or_create(
            year=year,
            defaults={
                "slug": f"ao{str(year)[-2:]}",
                "title": f"Аэрокосмическая олимпиада МФТИ {roman(year)}",
                "subtitle": f"Сезон {year - 1}/{str(year)[-2:]}",
                "is_published": True,
            },
        )
        return season
