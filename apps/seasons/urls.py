from django.urls import path

from . import views

app_name = "seasons"

urlpatterns = [
    path("second/", views.second_round, name="second_round"),
    path("final/", views.final, name="final"),
]
