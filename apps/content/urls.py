from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("news/", views.news_list, name="news_list"),
    path("news/<slug:slug>/", views.news_detail, name="news_detail"),
    path("lectures/", views.lecture_list, name="lecture_list"),
    path("lectures/archive/", views.lecture_archive, name="lecture_archive"),
    # Управление лекциями. Идут выше маршрута лекции, иначе «manage»
    # будет разобран как слаг сезона.
    path("lectures/manage/", views.lecture_manage, name="lecture_manage"),
    path("lectures/new/", views.lecture_new, name="lecture_new"),
    path("lectures/<int:pk>/edit/", views.lecture_edit, name="lecture_edit"),
    path("lectures/<slug:season_slug>/<slug:slug>/", views.lecture_detail, name="lecture_detail"),
    path("problems/", views.problem_archive, name="problem_archive"),
    path("page/<slug:slug>/", views.page, name="page"),
]
