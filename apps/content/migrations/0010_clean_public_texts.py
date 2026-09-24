"""Чистка текстов, которые видят участники.

* «Лекция отборочный тура.» → «Лекция отборочного тура.» (и финального);
* «Лекции сезона Сезон 2020/21» → «Лекции сезона 2020/2021»;
* служебная пометка «Укажите сезон в админке» в описании плейлиста;
* дубли плейлистов сезонов 2021/22 и 2023/24 (заведены дважды,
  по ссылке на видео и по ссылке на плейлист);
* в тренировочной задаче — пути на сервере и отсылки к админке.
"""

from django.db import migrations

PRACTICE_STATEMENT = (
    "<p>Это не настоящая задача олимпиады, а проверка связи: загрузите сюда "
    "любой файл — фото, PDF или текст — и нажмите «Отправить».</p>"
    "<p>Если после отправки на этой странице появилась карточка «Ваше последнее "
    "решение» с вашим файлом — всё работает, и во время тура решения будут "
    "доходить так же.</p>"
    "<p>Тренировочная задача открыта весь учебный год и на результаты не влияет. "
    "Отправлять можно сколько угодно раз.</p>"
)

DUPLICATE_PLAYLISTS = [
    "https://www.youtube.com/watch?v=Z5rYrIb1ER0&list=PLncYbc2UAdLEAZeQOiW2lOEslj-DzC2w8",
    "https://www.youtube.com/watch?v=qAsOZwt1UMs&list=PLncYbc2UAdLGmGDtn-7AEPIO5I2fMr12N",
]


def forwards(apps, schema_editor):
    Lecture = apps.get_model("content", "Lecture")
    Playlist = apps.get_model("content", "Playlist")
    Problem = apps.get_model("contest", "Problem")

    Lecture.objects.filter(description="Лекция отборочный тура.").update(
        description="Лекция отборочного тура.")
    Lecture.objects.filter(description="Лекция финальный тура.").update(
        description="Лекция финального тура.")

    Playlist.objects.filter(url__in=DUPLICATE_PLAYLISTS).delete()
    Playlist.objects.filter(description="Укажите сезон в админке").update(description="")
    for playlist in Playlist.objects.filter(title__startswith="Лекции сезона Сезон ").select_related("season"):
        if playlist.season:
            year = playlist.season.year
            playlist.title = f"Лекции сезона {year - 1}/{year}"
            playlist.save(update_fields=["title"])

    # Правим только нетронутый текст из демо: если его уже переписали
    # в админке, оставляем как есть.
    Problem.objects.filter(stage__is_practice=True,
                           statement_html__contains="media/solutions/").update(
        statement_html=PRACTICE_STATEMENT)


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0009_topic_alter_photo_options_lecture_topic"),
        ("contest", "0004_submissionfile_original_name"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
