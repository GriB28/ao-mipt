from django.urls import path

from . import views

app_name = "contest"

urlpatterns = [
    path("", views.problem_list, name="problem_list"),
    path("problem/<int:pk>/", views.problem_detail, name="problem_detail"),
    path("problem/<int:pk>/submit/", views.submit, name="submit"),
    path("my/", views.my_submissions, name="my_submissions"),
    path("file/<int:pk>/", views.submission_file, name="submission_file"),
    # Проверка решений организатором — прямо на сайте, без админки.
    path("review/", views.review_list, name="review_list"),
    path("review/<int:pk>/", views.review_detail, name="review_detail"),
    # Задачи: заводит организатор, одобряет администратор.
    path("problems/manage/", views.problem_manage, name="problem_manage"),
    path("problems/new/", views.problem_new, name="problem_new"),
    path("problems/<int:pk>/edit/", views.problem_edit, name="problem_edit"),
]
