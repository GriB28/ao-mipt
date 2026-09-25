"""Проверка здоровья контейнера сайта для Docker (healthcheck).

Ходит в gunicorn напрямую, минуя nginx. Host берём из ALLOWED_HOSTS:
на запрос с чужим именем Django ответил бы 400, и контейнер считался бы
больным, хотя всё работает.
"""

import os
import sys
import urllib.request

host = (os.environ.get("ALLOWED_HOSTS") or "localhost").split(",")[0].strip() or "localhost"
request = urllib.request.Request("http://127.0.0.1:8000/healthz/", headers={"Host": host})
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception as exc:
    print(exc)
    sys.exit(1)
