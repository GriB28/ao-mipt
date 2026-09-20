from django.urls import path

from . import views

app_name = "venues"

urlpatterns = [
    path("", views.venue_map, name="map"),
    path("venues.geojson", views.venues_geojson, name="geojson"),
    path("venue/<int:pk>/", views.venue_detail, name="detail"),
    path("venue/<int:pk>/book/", views.book_venue, name="book"),
    path("venue/<int:pk>/cancel/", views.cancel_booking, name="cancel_booking"),
    # Ведомость площадки: список участников, баллы, итоги.
    path("venue/<int:pk>/edit/", views.venue_edit, name="edit"),
    path("venue/<int:pk>/mail/", views.venue_mail, name="mail"),
    path("venue/<int:pk>/participants/", views.venue_participants, name="participants"),
    path("venue/<int:pk>/results/", views.venue_results, name="results"),
    path("venue/<int:pk>/publish-results/", views.publish_results, name="publish_results"),
    path("apply/", views.apply_venue, name="apply"),
    path("apply/done/", views.apply_done, name="apply_done"),
]
