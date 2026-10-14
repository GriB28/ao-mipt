"""
Склонение числительных и наименований моделей в русском языке.
"""

from typing import Any, Tuple


def plural_ru(n: Any, one: str, few: str, many: str) -> str:
    """
    Выбирает правильную форму слова в зависимости от числа:
    - one: 1, 21, 31, 101... (но не 11)
    - few: 2, 3, 4, 22, 23, 24, 102... (но не 12..14)
    - many: 0, 5..20, 25..30, 11..14...
    """
    try:
        val = abs(int(n))
    except (ValueError, TypeError):
        return many

    val_100 = val % 100
    val_10 = val % 10

    if 11 <= val_100 <= 19:
        return many
    if val_10 == 1:
        return one
    if 2 <= val_10 <= 4:
        return few
    return many


pluralize_ru = plural_ru


#: Точные формы для всех моделей проекта: (1, 2, 5)
MODEL_PLURAL_FORMS = {
    # Рассылки и письма
    ("mailing", "delivery"): ("письмо", "письма", "писем"),
    ("mailing", "newsletter"): ("рассылка", "рассылки", "рассылок"),
    # Учётные записи и анкеты
    ("accounts", "user"): ("пользователь", "пользователя", "пользователей"),
    ("accounts", "organizerprofile"): ("анкета организатора", "анкеты организатора", "анкет организаторов"),
    ("accounts", "participantprofile"): ("анкета участника", "анкеты участника", "анкет участников"),
    ("accounts", "consentdocument"): ("согласие на обработку ПД", "согласия на обработку ПД", "согласий на обработку ПД"),
    # Контент
    ("content", "news"): ("новость", "новости", "новостей"),
    ("content", "playlist"): ("плейлист", "плейлиста", "плейлистов"),
    ("content", "lecture"): ("лекция", "лекции", "лекций"),
    ("content", "page"): ("страница", "страницы", "страниц"),
    ("content", "archivematerial"): ("материал архива", "материала архива", "материалов архива"),
    ("content", "photo"): ("фотография", "фотографии", "фотографий"),
    ("content", "topic"): ("тема лекций", "темы лекций", "тем лекций"),
    # Олимпиада и задачи
    ("contest", "problem"): ("задача", "задачи", "задач"),
    ("contest", "problemattachment"): ("материал к задаче", "материала к задаче", "материалов к задаче"),
    ("contest", "submission"): ("решение", "решения", "решений"),
    ("contest", "submissionfile"): ("файл решения", "файла решений", "файлов решений"),
    ("contest", "grade"): ("оценка", "оценки", "оценок"),
    ("contest", "score"): ("балл за задачу", "балла за задачу", "баллов за задачи"),
    # Сезоны
    ("seasons", "season"): ("сезон", "сезона", "сезонов"),
    ("seasons", "stage"): ("этап", "этапа", "этапов"),
    # Площадки
    ("venues", "venue"): ("площадка", "площадки", "площадок"),
    # Участие
    ("participation", "registration"): ("участие в сезоне", "участия в сезоне", "участий в сезоне"),
    ("participation", "venuebooking"): ("запись на площадку", "записи на площадку", "записей на площадки"),
    # Встроенные модели Django
    ("auth", "group"): ("группа", "группы", "групп"),
    ("auth", "permission"): ("право", "права", "прав"),
    ("admin", "logentry"): ("запись журнала", "записи журнала", "записей журнала"),
}


NOUN_PLURAL_FORMS = {
    "письмо": ("письмо", "письма", "писем"),
    "рассылка": ("рассылка", "рассылки", "рассылок"),
    "пользователь": ("пользователь", "пользователя", "пользователей"),
    "анкета организатора": ("анкета организатора", "анкеты организатора", "анкет организаторов"),
    "анкета участника": ("анкета участника", "анкеты участника", "анкет участников"),
    "согласие на обработку пд": ("согласие на обработку ПД", "согласия на обработку ПД", "согласий на обработку ПД"),
    "новость": ("новость", "новости", "новостей"),
    "плейлист": ("плейлист", "плейлиста", "плейлистов"),
    "лекция": ("лекция", "лекции", "лекций"),
    "страница": ("страница", "страницы", "страниц"),
    "материал архива": ("материал архива", "материала архива", "материалов архива"),
    "материал к задаче": ("материал к задаче", "материала к задаче", "материалов к задаче"),
    "фотография": ("фотография", "фотографии", "фотографий"),
    "тема лекций": ("тема лекций", "темы лекций", "тем лекций"),
    "задача": ("задача", "задачи", "задач"),
    "решение": ("решение", "решения", "решений"),
    "файл решения": ("файл решения", "файла решений", "файлов решений"),
    "оценка": ("оценка", "оценки", "оценок"),
    "балл за задачу": ("балл за задачу", "балла за задачу", "баллов за задачи"),
    "сезон": ("сезон", "сезона", "сезонов"),
    "этап": ("этап", "этапа", "этапов"),
    "площадка": ("площадка", "площадки", "площадок"),
    "участие в сезоне": ("участие в сезоне", "участия в сезоне", "участий в сезоне"),
    "запись на площадку": ("запись на площадку", "записи на площадку", "записей на площадки"),
    "группа": ("группа", "группы", "групп"),
    "право": ("право", "права", "прав"),
    "запись журнала": ("запись журнала", "записи журнала", "записей журнала"),
    "человек": ("человек", "человека", "человек"),
    "получатель": ("получатель", "получателя", "получателей"),
    "день": ("день", "дня", "дней"),
    "ошибка": ("ошибка", "ошибки", "ошибок"),
    "строка": ("строка", "строки", "строк"),
    "файл": ("файл", "файла", "файлов"),
    "объект": ("объект", "объекта", "объектов"),
}


#: Формы винительного падежа (кого? что?): "Добавить рассылку", "Добавить площадку"
MODEL_ACCUSATIVE_FORMS = {
    # Рассылки и письма
    ("mailing", "delivery"): "письмо",
    ("mailing", "newsletter"): "рассылку",
    # Учётные записи и анкеты
    ("accounts", "user"): "пользователя",
    ("accounts", "organizerprofile"): "анкету организатора",
    ("accounts", "participantprofile"): "анкету участника",
    ("accounts", "consentdocument"): "согласие на обработку ПД",
    # Контент
    ("content", "news"): "новость",
    ("content", "playlist"): "плейлист",
    ("content", "lecture"): "лекцию",
    ("content", "page"): "страницу",
    ("content", "archivematerial"): "материал архива",
    ("content", "photo"): "фотографию",
    ("content", "topic"): "тему лекций",
    # Олимпиада и задачи
    ("contest", "problem"): "задачу",
    ("contest", "problemattachment"): "материал к задаче",
    ("contest", "submission"): "решение",
    ("contest", "submissionfile"): "файл решения",
    ("contest", "grade"): "оценку",
    ("contest", "score"): "балл за задачу",
    # Сезоны
    ("seasons", "season"): "сезон",
    ("seasons", "stage"): "этап",
    # Площадки
    ("venues", "venue"): "площадку",
    # Участие
    ("participation", "registration"): "участие в сезоне",
    ("participation", "venuebooking"): "запись на площадку",
    # Встроенные модели
    ("auth", "group"): "группу",
    ("auth", "permission"): "право",
    ("admin", "logentry"): "запись журнала",
}


NOUN_ACCUSATIVE_FORMS = {
    "рассылка": "рассылку",
    "письмо": "письмо",
    "пользователь": "пользователя",
    "анкета организатора": "анкету организатора",
    "анкета участника": "анкету участника",
    "согласие на обработку пд": "согласие на обработку ПД",
    "новость": "новость",
    "плейлист": "плейлист",
    "лекция": "лекцию",
    "страница": "страницу",
    "материал архива": "материал архива",
    "материал к задаче": "материал к задаче",
    "фотография": "фотографию",
    "тема лекций": "тему лекций",
    "задача": "задачу",
    "решение": "решение",
    "файл решения": "файл решения",
    "оценка": "оценку",
    "балл за задачу": "балл за задачу",
    "сезон": "сезон",
    "этап": "этап",
    "площадка": "площадку",
    "участие в сезоне": "участие в сезоне",
    "запись на площадку": "запись на площадку",
    "группа": "группу",
    "право": "право",
    "запись журнала": "запись журнала",
}


def noun_to_accusative(text: str) -> str:
    """
    Преобразует существительное (или словосочетание) в винительный падеж.
    Например: "рассылка" -> "рассылку", "площадка" -> "площадку".
    """
    if not text:
        return text

    low = text.strip().lower()
    if low in NOUN_ACCUSATIVE_FORMS:
        return NOUN_ACCUSATIVE_FORMS[low]

    words = text.strip().split(maxsplit=1)
    first = words[0]
    rest = (" " + words[1]) if len(words) > 1 else ""

    if first.endswith("ия"):
        return first[:-2] + "ию" + rest
    elif first.endswith("а"):
        return first[:-1] + "у" + rest
    elif first.endswith("я"):
        return first[:-1] + "ю" + rest
    elif first.lower() == "пользователь":
        return "пользователя" + rest

    return text


def get_model_plural(opts: Any, n: int) -> str:
    """
    Возвращает наименование модели в нужной грамматической форме для количества n.
    """
    if hasattr(opts, "_meta"):
        opts = opts._meta

    app_label = getattr(opts, "app_label", None)
    model_name = getattr(opts, "model_name", None)

    forms = None
    if app_label and model_name:
        forms = MODEL_PLURAL_FORMS.get((app_label, model_name))

    if not forms and hasattr(opts, "verbose_name"):
        vn = str(opts.verbose_name).strip().lower()
        forms = NOUN_PLURAL_FORMS.get(vn)

    if forms:
        return plural_ru(n, forms[0], forms[1], forms[2])

    if n == 1:
        return str(getattr(opts, "verbose_name", ""))
    return str(getattr(opts, "verbose_name_plural", ""))


def get_model_accusative(opts: Any) -> str:
    """
    Возвращает наименование модели в винительном падеже (кого? что?):
    "рассылку", "площадку", "пользователя", "задачу".
    """
    if hasattr(opts, "_meta"):
        opts = opts._meta

    app_label = getattr(opts, "app_label", None)
    model_name = getattr(opts, "model_name", None)

    if app_label and model_name:
        form = MODEL_ACCUSATIVE_FORMS.get((app_label, model_name))
        if form:
            return form

    vn = str(getattr(opts, "verbose_name", "")).strip()
    return noun_to_accusative(vn)


def patch_admin_interface_declensions() -> None:
    """
    Патчит админку Django для правильного склонения в русском интерфейсе:
    1. model_ngettext (счётчики при массовых действиях: "6 писем", "6 рассылок").
    2. render_change_form (заголовки страниц: "Добавить рассылку", "Изменить рассылку").
    3. _delete_view (подтверждение удаления: "удалить рассылку «...»?").
    """
    import django.contrib.admin.actions
    import django.contrib.admin.options
    import django.contrib.admin.utils
    from django.contrib.admin import ModelAdmin

    # --- 1. model_ngettext ---
    def custom_model_ngettext(obj, n=None):
        from django.db import models

        if isinstance(obj, models.query.QuerySet):
            if n is None:
                n = obj.count()
            obj = obj.model

        opts = getattr(obj, "_meta", obj)
        if n is None:
            # Для множественного числа без конкретной цифры
            # одушевлённые в винительном совпадают с родительным ("пользователей"),
            # неодушевлённые — с именительным ("рассылки", "письма").
            if getattr(opts, "model_name", "") == "user":
                return "пользователей"
            return str(getattr(opts, "verbose_name_plural", ""))

        if n == 1:
            return get_model_accusative(opts)

        return get_model_plural(opts, n)

    django.contrib.admin.utils.model_ngettext = custom_model_ngettext
    django.contrib.admin.actions.model_ngettext = custom_model_ngettext
    django.contrib.admin.options.model_ngettext = custom_model_ngettext

    # --- 2. render_change_form (заголовок страницы добавления/редактирования) ---
    orig_render_change_form = ModelAdmin.render_change_form

    def custom_render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        acc = get_model_accusative(self.opts)
        if add:
            context["title"] = f"Добавить {acc}"
        elif change:
            if self.has_change_permission(request, obj):
                context["title"] = f"Изменить {acc}"
            else:
                context["title"] = f"Просмотреть {acc}"
        return orig_render_change_form(self, request, context, add=add, change=change, form_url=form_url, obj=obj)

    ModelAdmin.render_change_form = custom_render_change_form

    # --- 3. _delete_view (подтверждение удаления одиночного объекта) ---
    orig_delete_view = ModelAdmin._delete_view

    def custom_delete_view(self, request, object_id, extra_context):
        res = orig_delete_view(self, request, object_id, extra_context)
        if hasattr(res, "context_data") and res.context_data:
            acc = get_model_accusative(self.opts)
            res.context_data["object_name"] = acc
            if "title" in res.context_data and res.context_data["title"].startswith("Не удается"):
                res.context_data["title"] = f"Не удается удалить {acc}"
        return res

    ModelAdmin._delete_view = custom_delete_view


patch_admin_model_ngettext = patch_admin_interface_declensions
