from django.http import HttpResponseRedirect, JsonResponse


class AdminAjaxListEditableMiddleware:
    """Перехватывает AJAX-сохранение списков в админке Django и возвращает JSON вместо 302 редиректа."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.path.startswith("/admin/")
            and request.method == "POST"
            and request.headers.get("x-requested-with") == "XMLHttpRequest"
            and isinstance(response, HttpResponseRedirect)
        ):
            return JsonResponse({"status": "ok", "message": "Сохранено"})
        return response
