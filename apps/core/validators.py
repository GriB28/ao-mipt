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


def validate_solution_file(file):
    validate_upload_size(file)
    ext = Path(file.name).suffix.lower()
    if ext not in ALLOWED_SOLUTION_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_SOLUTION_EXTENSIONS))
        raise ValidationError(f"Формат {ext or '—'} не принимается. Разрешены: {allowed}")
