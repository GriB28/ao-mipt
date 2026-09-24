"""Проверки загружаемых файлов. Общие для задач и решений."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_SOLUTION_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png",          # скан или фото решения
    ".py", ".ipynb", ".cpp", ".c", ".h", ".java", ".txt", ".csv",  # код и данные
    ".zip",
}


def validate_upload_size(file):
    limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file.size > limit:
        raise ValidationError(f"Файл больше {settings.MAX_UPLOAD_SIZE_MB} МБ. Сожмите или разбейте его.")


#: Скан согласия: только то, что можно открыть и прочитать глазами.
ALLOWED_CONSENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def validate_participant_upload_size(file):
    """Предел для файлов школьников (решения, сканы согласий).

    Меньше, чем у организаторов: участников тысячи, и каждый лишний
    мегабайт умножается на число попыток. Фотографии браузер сжимает
    сам перед отправкой (static/js/compress.js), так что снимок страницы
    с телефона в предел укладывается.
    """
    limit = settings.PARTICIPANT_UPLOAD_MAX_MB
    if file.size > limit * 1024 * 1024:
        raise ValidationError(
            f"Файл «{Path(file.name).name}» больше {limit:g} МБ. "
            "Сфотографируйте страницу заново или сохраните PDF в меньшем качестве."
        )


def _validate_extension(file, allowed):
    ext = Path(file.name).suffix.lower()
    if ext not in allowed:
        raise ValidationError(
            f"Формат {ext or '—'} не принимается. Разрешены: {', '.join(sorted(allowed))}"
        )


def validate_solution_file(file):
    validate_participant_upload_size(file)
    _validate_extension(file, ALLOWED_SOLUTION_EXTENSIONS)


def validate_consent_file(file):
    validate_participant_upload_size(file)
    _validate_extension(file, ALLOWED_CONSENT_EXTENSIONS)
