from django.urls import path

from . import views

app_name = "venues"

urlpatterns = [
    path("", views.venue_map, name="map"),
    path("venues.geojson", views.venues_geojson, name="geojson"),
    path("booking/<int:pk>/scan/", views.offline_work_scan, name="work_scan"),
    path("booking/<int:pk>/upload-scan/", views.upload_offline_work_scan, name="upload_work_scan_item"),
    path("upload-scan/", views.upload_offline_work_scan, name="upload_work_scan"),
    path("booking/<int:pk>/delete-scan/", views.delete_offline_work_scan, name="delete_work_scan"),
    path("save-scores/", views.offline_save_scores, name="save_scores"),
    path("venue/<int:pk>/", views.venue_detail, name="detail"),
    path("venue/<int:pk>/book/", views.book_venue, name="book"),
    path("venue/<int:pk>/cancel/", views.cancel_booking, name="cancel_booking"),
    # Ведомость площадки: список участников, баллы, итоги.
    path("venue/<int:pk>/edit/", views.venue_edit, name="edit"),
    path("venue/<int:pk>/mail/", views.venue_mail, name="mail"),
    path("venue/<int:pk>/participants/", views.venue_participants, name="participants"),
    path("venue/<int:pk>/results/", views.venue_results, name="results"),
    path("venue/<int:pk>/publish-results/", views.publish_results, name="publish_results"),
    path("venue/<int:pk>/export/", views.venue_export, name="export"),
    path("venue/<int:pk>/export-participants/", views.venue_export, name="export_participants"),
    path("apply/", views.apply_venue, name="apply"),
    path("apply/done/", views.apply_done, name="apply_done"),
]
