from django.conf import settings


def site_settings(request):
    """Публичные настройки из .env, нужные в шаблонах."""
    return {
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
        "TELEGRAM_URL": settings.TELEGRAM_URL,
        "TELEGRAM_CHAT_URL": settings.TELEGRAM_CHAT_URL,
        "VK_URL": settings.VK_URL,
        "MAX_URL": settings.MAX_URL,
        "PRIVACY_POLICY_URL": settings.PRIVACY_POLICY_URL,
        "OLYMPIAD_ORDER_URL": settings.OLYMPIAD_ORDER_URL,
        "OLYMPIAD_STATUTE_URL": settings.OLYMPIAD_STATUTE_URL,
        "OLYMPIAD_REGULATIONS_URL": settings.OLYMPIAD_REGULATIONS_URL,
        "YANDEX_MAPS_API_KEY": settings.YANDEX_MAPS_API_KEY,
    }
