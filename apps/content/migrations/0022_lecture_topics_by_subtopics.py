"""Лекции: темы уточнены по столбцу «подтемы» таблицы организаторов
(октябрь 2026), в описания добавлены подтемы, у лекций появилась ссылка
на блокнот.

Новые темы: «Колебания, волны и сигналы», «Ракеты и реактивное движение»,
«Излучение и астрофизика»; несколько тем переименованы. Тему и описание
лекции меняем, только если они те же, что завёл каталог, — поправленное
в админке не трогаем. Каталог — apps/content/lecture_catalog.py.
"""

from django.db import migrations, models

#: Прежние названия тем — переименовываем, только если их не меняли в админке.
OLD_TITLES = {
    'solutions': 'Разборы задач',
    'about': 'Об олимпиаде',
    'mechanics': 'Механика',
    'celestial': 'Небесная механика и баллистика',
    'fluids': 'Гидро- и аэродинамика',
    'thermo': 'Термодинамика и атмосфера',
    'electricity': 'Электричество и магнетизм',
    'optics': 'Оптика и излучение',
    'math': 'Математический аппарат',
    'python': 'Основы Python',
    'numerical': 'Численные методы',
    'algorithms': 'Алгоритмы',
    'data': 'Данные, статистика и машинное обучение',
}

#: Лекции, сменившие тему: ссылка на видео → (была, стала).
MOVES = {
    'https://youtu.be/HEyjdQXjZTw?si=rDjx28MKEEVoike9': ('mechanics', 'numerical'),
    'https://youtu.be/IMy-x-7jEqY?si=HnRT8BzGgr8cm26X': ('celestial', 'rockets'),
    'https://youtu.be/6ROUS-ADK1g?si=RTiPNfOduBApTHTi': ('mechanics', 'numerical'),
    'https://youtu.be/LnBu_TXDD4Y?si=-PmrRVvSTfKMJVzr': ('celestial', 'rockets'),
    'https://youtu.be/_2oMk6B5w5A?si=Q-D-uUdZr60hJ51f': ('optics', 'astro'),
    'https://youtu.be/OEuRiTIjy8g?si=btQeKzRIhogAyS6h': ('celestial', 'rockets'),
    'https://vkvideo.ru/video-17906_456239206': ('optics', 'astro'),
    'https://vkvideo.ru/video-17906_456239208': ('mechanics', 'oscillations'),
    'https://vkvideo.ru/video-17906_456239246': ('optics', 'oscillations'),
    'https://vkvideo.ru/video-17906_456239250': ('celestial', 'rockets'),
}

#: Описания, которые завёл прежний каталог, — их заменяем на новые.
OLD_DESCRIPTIONS = {"", "Лекция отборочного тура.", "Лекция финального тура."}


def forwards(apps, schema_editor):
    from apps.content.lecture_catalog import LECTURES, TOPICS

    Topic = apps.get_model("content", "Topic")
    Lecture = apps.get_model("content", "Lecture")
    if not Lecture.objects.exists():
        return  # каталог заведёт seed_lectures уже в новом виде

    topics = {}
    for slug, title, section, order in TOPICS:
        topic = Topic.objects.filter(slug=slug).first()
        if topic is None:
            topic = Topic.objects.create(slug=slug, title=title, section=section, order=order)
        elif topic.title == OLD_TITLES.get(slug, topic.title):
            topic.title, topic.order = title, order
            topic.save(update_fields=["title", "order"])
        topics[slug] = topic

    for _, slug, _, _, url, description, *rest in LECTURES:
        notebook = rest[0] if rest else ""
        for lecture in Lecture.objects.filter(video_url=url).select_related("topic"):
            fields = []
            move = MOVES.get(url)
            if move and lecture.topic and lecture.topic.slug == move[0]:
                lecture.topic = topics[move[1]]
                fields.append("topic")
            if notebook and not lecture.notebook_url:
                lecture.notebook_url = notebook
                fields.append("notebook_url")
            if lecture.description in OLD_DESCRIPTIONS and description != lecture.description:
                lecture.description = description
                fields.append("description")
            if fields:
                lecture.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [("content", "0021_consents_after_mipt_lawyer")]

    operations = [
        migrations.AddField(
            model_name="lecture",
            name="notebook_url",
            field=models.URLField(
                blank=True, verbose_name="ссылка на блокнот",
                help_text="Блокнот с кодом или конспектом лекции: Google Drive, Colab, GitHub"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
