"""
Заводит темы, лекции и плейлисты прошлых сезонов из каталога в коде.

    python manage.py seed_lectures

Вызывается из seed_demo, отдельно нужна редко. Идемпотентна: повторный
запуск ничего не задваивает, лекция опознаётся по сезону и ссылке.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.content.lecture_catalog import LECTURES, SEASON_PLAYLISTS, TOPICS
from apps.content.models import Lecture, Playlist, Topic
from apps.seasons.models import Season


class Command(BaseCommand):
    help = "Наполняет каталог лекций из apps/content/lecture_catalog.py"

    @transaction.atomic
    def handle(self, *args, **options):
        topics = {}
        for slug, title, section, order in TOPICS:
            topics[slug], _ = Topic.objects.update_or_create(
                slug=slug,
                defaults={"title": title, "section": section, "order": order},
            )

        created = skipped = 0
        for position, (year, topic_slug, title, lecturer, url, note) in enumerate(LECTURES):
            season = self._season(year)
            # Ссылка на видео уникальна и не меняется — по ней и узнаём,
            # заводили мы уже эту лекцию или нет.
            if Lecture.objects.filter(season=season, video_url=url).exists():
                skipped += 1
                continue
            Lecture.objects.create(
                season=season,
                slug=self._slug(season, title, position),
                title=title,
                lecturer=lecturer,
                video_url=url,
                description=note,
                topic=topics.get(topic_slug),
                status=Lecture.Status.APPROVED,
            )
            created += 1

        playlists = 0
        for year, url in SEASON_PLAYLISTS:
            season = self._season(year)
            _, was_created = Playlist.objects.get_or_create(
                url=url,
                defaults={
                    "title": f"Лекции сезона {season.years_label}",
                    "season": season,
                    "description": "Все записи сезона одним плейлистом",
                    "order": year,
                },
            )
            playlists += int(was_created)

        self.stdout.write(self.style.SUCCESS(
            f"Лекции: создано {created}, уже были {skipped}. Плейлистов добавлено: {playlists}"
        ))

    def _slug(self, season, title, position):
        """Адрес лекции, уникальный внутри сезона.

        slugify выбрасывает кириллицу, поэтому у «Знакомство с Python.
        Функции» и «Знакомство с Python. Numpy» получается один и тот же
        «python» — дописываем номер, пока не станет уникальным.
        """
        base = slugify(title) or f"lecture-{position + 1}"
        slug, number = base, 1
        while Lecture.objects.filter(season=season, slug=slug).exists():
            number += 1
            slug = f"{base}-{number}"
        return slug

    def _season(self, year):
        from apps.content.management.commands.import_archive import roman

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
