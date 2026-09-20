from .models import Season


def current_season(request):
    """Активный сезон доступен во всех шаблонах как {{ current_season }}."""
    return {"current_season": Season.objects.active()}
