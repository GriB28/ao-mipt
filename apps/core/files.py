"""Отдача закрытых файлов (решения, сканы согласий) после проверки прав.

Права проверяет вызывающее представление. Здесь — только сама отдача:
в проде файл передаёт nginx (X-Accel-Redirect на internal-location,
см. deploy/nginx/locations.conf), локально — Django.
"""

import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

# Эти форматы браузер показывает сам, остальное — только скачиванием.
INLINE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".txt", ".csv"}


def protected_file_response(request, fieldfile, filename):
    if not fieldfile or not fieldfile.storage.exists(fieldfile.name):
        raise Http404
    inline = Path(filename).suffix.lower() in INLINE_EXTENSIONS and "download" not in request.GET
    accel = settings.PROTECTED_MEDIA_ACCEL_PREFIX
    if accel:
        response = HttpResponse()
        response["X-Accel-Redirect"] = accel.rstrip("/") + "/" + quote(fieldfile.name)
        # Тип nginx определит по расширению сам.
        del response["Content-Type"]
        disposition = "inline" if inline else "attachment"
        response["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{quote(filename)}"
    else:
        content_type, _ = mimetypes.guess_type(filename)
        response = FileResponse(fieldfile.open("rb"), as_attachment=not inline, filename=filename,
                                content_type=content_type or "application/octet-stream")
    # Файл прислал человек: запрещаем браузеру угадывать тип. Открываются
    # в браузере только PDF, картинки и текст, HTML и SVG не принимаются.
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
