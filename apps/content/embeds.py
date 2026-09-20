"""
Превращение ссылки на видео в адрес для встраивания в страницу.

Поддерживаем то, чем пользуется олимпиада: ВКонтакте (основная площадка
для лекций), YouTube и Rutube. Ссылку организатор просто копирует из
адресной строки — разбираться в форматах встраивания он не должен.
"""

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
VK_HOSTS = {"vk.com", "www.vk.com", "vkvideo.ru", "www.vkvideo.ru"}
RUTUBE_HOSTS = {"rutube.ru", "www.rutube.ru"}

# vk.com/video-17906_456239123  или  vkvideo.ru/video-17906_456239123
VK_VIDEO_RE = re.compile(r"video(-?\d+)_(\d+)")
# vkvideo.ru/playlist/-17906_48144875
VK_PLAYLIST_RE = re.compile(r"playlist/(-?\d+)_(\d+)")
RUTUBE_RE = re.compile(r"/video/([0-9a-f]{32})")


def detect_platform(url: str) -> str:
    """Возвращает код площадки: youtube, vk, rutube или other."""
    if not url:
        return "other"
    host = (urlparse(url).hostname or "").lower()
    if host in YOUTUBE_HOSTS:
        return "youtube"
    if host in VK_HOSTS:
        return "vk"
    if host in RUTUBE_HOSTS:
        return "rutube"
    return "other"


def embed_url(url: str) -> str | None:
    """
    Адрес для <iframe>. None — если ссылку встроить нельзя
    (например, это плейлист ВКонтакте: их плеер целиком не встраивается).
    """
    if not url:
        return None

    platform = detect_platform(url)
    parsed = urlparse(url)

    if platform == "youtube":
        return _youtube_embed(parsed)
    if platform == "vk":
        return _vk_embed(url)
    if platform == "rutube":
        match = RUTUBE_RE.search(parsed.path)
        return f"https://rutube.ru/play/embed/{match.group(1)}" if match else None
    return None


def _youtube_embed(parsed) -> str | None:
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)

    if "youtu.be" in host:
        video_id = parsed.path.lstrip("/")
    else:
        video_id = (query.get("v") or [""])[0]

    playlist = (query.get("list") or [""])[0]

    if video_id:
        base = f"https://www.youtube-nocookie.com/embed/{video_id}"
        return f"{base}?list={playlist}" if playlist else base
    if playlist:
        # Ссылка на плейлист без конкретного ролика — встраиваем плейлист.
        return f"https://www.youtube-nocookie.com/embed/videoseries?list={playlist}"
    return None


def _vk_embed(url: str) -> str | None:
    # Плейлист ВКонтакте встроить нельзя — отдаём None, шаблон покажет ссылку.
    if VK_PLAYLIST_RE.search(url):
        return None
    match = VK_VIDEO_RE.search(url)
    if not match:
        return None
    owner_id, video_id = match.groups()
    return f"https://vk.com/video_ext.php?oid={owner_id}&id={video_id}&hd=2"


def platform_title(platform: str) -> str:
    return {
        "youtube": "YouTube",
        "vk": "ВКонтакте",
        "rutube": "Rutube",
    }.get(platform, "Видео")
