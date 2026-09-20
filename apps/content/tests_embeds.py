"""Разбор ссылок на видео: организатор копирует адрес из строки браузера."""

from django.test import TestCase

from apps.content.embeds import detect_platform, embed_url


class DetectPlatformTest(TestCase):
    def test_known_platforms(self):
        cases = [
            ("https://www.youtube.com/watch?v=Z5rYrIb1ER0", "youtube"),
            ("https://youtu.be/Z5rYrIb1ER0", "youtube"),
            ("https://vkvideo.ru/playlist/-17906_48144875", "vk"),
            ("https://vk.com/video-17906_456239123", "vk"),
            ("https://rutube.ru/video/" + "a" * 32 + "/", "rutube"),
            ("https://example.com/video", "other"),
            ("", "other"),
        ]
        for url, expected in cases:
            self.assertEqual(detect_platform(url), expected, url)


class EmbedUrlTest(TestCase):
    def test_youtube_video_with_playlist(self):
        url = "https://www.youtube.com/watch?v=Z5rYrIb1ER0&list=PLncYbc2UAdLEAZeQOiW2lOEslj-DzC2w8"
        self.assertEqual(
            embed_url(url),
            "https://www.youtube-nocookie.com/embed/Z5rYrIb1ER0"
            "?list=PLncYbc2UAdLEAZeQOiW2lOEslj-DzC2w8",
        )

    def test_youtube_short_link(self):
        self.assertEqual(
            embed_url("https://youtu.be/qAsOZwt1UMs"),
            "https://www.youtube-nocookie.com/embed/qAsOZwt1UMs",
        )

    def test_youtube_playlist_only(self):
        self.assertEqual(
            embed_url("https://www.youtube.com/playlist?list=PLabc"),
            "https://www.youtube-nocookie.com/embed/videoseries?list=PLabc",
        )

    def test_vk_video(self):
        self.assertEqual(
            embed_url("https://vkvideo.ru/video-17906_456239123"),
            "https://vk.com/video_ext.php?oid=-17906&id=456239123&hd=2",
        )

    def test_vk_playlist_cannot_be_embedded(self):
        """Плейлист ВК плеером не встраивается — показываем ссылку."""
        self.assertIsNone(embed_url("https://vkvideo.ru/playlist/-17906_48144875"))

    def test_rutube(self):
        h = "0123456789abcdef0123456789abcdef"
        self.assertEqual(embed_url(f"https://rutube.ru/video/{h}/"),
                         f"https://rutube.ru/play/embed/{h}")

    def test_unknown_and_empty(self):
        self.assertIsNone(embed_url("https://example.com/v"))
        self.assertIsNone(embed_url(""))
