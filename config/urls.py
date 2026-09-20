from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("offline/", include("apps.venues.urls")),
    path("online/", include("apps.contest.urls")),
    path("", include("apps.seasons.urls")),
    path("", include("apps.content.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Аэрокосмическая олимпиада МФТИ"
admin.site.site_title = "АО МФТИ"
admin.site.index_title = "Управление олимпиадой"
