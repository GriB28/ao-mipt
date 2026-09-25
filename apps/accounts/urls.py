from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("signup/done/", views.signup_done, name="signup_done"),
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html",
                                                authentication_form=LoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    # Согласие на обработку ПД: бланк из анкеты, загрузка скана, сам скан.
    path("consent/blank.pdf", views.consent_blank, name="consent_blank"),
    path("consent/upload/", views.consent_upload, name="consent_upload"),
    path("consent/<int:pk>/file/", views.consent_file, name="consent_file"),
    # Подтверждение почты: ссылка из письма и кнопка «отправить ещё раз».
    # «resend» раньше токена: иначе confirm/<token>/ принимает его за токен.
    path("confirm/resend/", views.resend_confirmation, name="resend_confirmation"),
    path("confirm/<str:token>/", views.confirm_email, name="confirm_email"),
    # Восстановление пароля — готовые view Django, нужны только шаблоны.
    path("password-reset/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset_form.html",
        email_template_name="accounts/password_reset_email.txt",
        success_url="/accounts/password-reset/done/",
    ), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.PasswordResetConfirm.as_view(
        template_name="accounts/password_reset_confirm.html",
        success_url="/accounts/reset/done/"), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
]
