"""
Формы ручной записи участника на точку проведения очного тура.
"""

from django import forms
from django.db import models

from apps.accounts.models import User
from apps.seasons.models import Season, Stage
from apps.venues.models import Venue

from .models import Registration, VenueBooking


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        profile = getattr(obj, "profile", None)
        full_name = profile.full_name if profile else ""
        if full_name:
            return f"{full_name} ({obj.email})"
        return obj.email


class SeasonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        active_tag = " ★" if obj.is_active else ""
        return f"{obj.title} ({obj.years_label}){active_tag}"


class StageChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.title


class VenueChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        lock_tag = " [запись заблокирована]" if obj.registration_closed else ""
        return f"{obj.title} ({obj.city}){lock_tag}"


class VenueBookingAdminForm(forms.ModelForm):
    """
    Форма ручной записи участника на точку проведения очного этапа.

    1. Выбор участника из выпадающего списка с поиском по ФИО.
    2. Выбор сезона → этапы и точки обновляются динамически через JS.
    3. Выбор очного этапа и точки проведения.
    """

    user = UserChoiceField(
        queryset=User.objects.select_related("profile").filter(
            role=User.Role.PARTICIPANT
        ).order_by(
            models.Case(
                models.When(profile__last_name="", then=models.Value(1)),
                models.When(profile__last_name__isnull=True, then=models.Value(1)),
                default=models.Value(0),
            ),
            "profile__last_name",
            "profile__first_name",
            "email",
        ),
        required=True,
        label="Участник",
        help_text="Выберите участника из списка или начните вводить фамилию.",
        widget=forms.Select(attrs={"style": "width: 100%; max-width: 500px;"}),
    )
    season = SeasonChoiceField(
        queryset=Season.objects.all().order_by("-year"),
        required=True,
        label="Сезон",
    )
    stage = StageChoiceField(
        queryset=Stage.objects.none(),  # заполняется в __init__
        required=True,
        label="Очный этап",
    )
    venue = VenueChoiceField(
        queryset=Venue.objects.none(),  # заполняется в __init__
        required=True,
        label="Точка проведения",
    )
    status = forms.ChoiceField(
        choices=VenueBooking.Status.choices,
        initial=VenueBooking.Status.BOOKED,
        label="Статус",
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
        label="Комментарий",
    )

    class Meta:
        model = VenueBooking
        fields = ("stage", "venue", "status", "comment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["user", "season", "stage", "venue", "status", "comment"])

        # Определяем выбранный сезон: из POST-данных → экземпляра → начальных данных → активного
        chosen_season = None

        # 1) POST-данные имеют наивысший приоритет (пользователь мог сменить сезон через JS)
        post_season_id = self.data.get("season") if self.data else None
        if post_season_id:
            try:
                chosen_season = Season.objects.get(pk=post_season_id)
            except Season.DoesNotExist:
                pass

        if chosen_season is None:
            if self.instance and self.instance.pk:
                # Редактирование существующей записи
                chosen_season = self.instance.registration.season
                self.fields["user"].initial = self.instance.registration.user_id
                self.fields["season"].initial = self.instance.registration.season_id
                self.fields["stage"].initial = self.instance.stage_id
                self.fields["venue"].initial = self.instance.venue_id
                self.fields["status"].initial = self.instance.status
                self.fields["comment"].initial = self.instance.comment
            else:
                # Создание новой записи: берём пользователя и сезон из начальных данных
                initial_user_id = self.initial.get("user")
                if initial_user_id:
                    try:
                        self.fields["user"].initial = int(initial_user_id)
                    except (ValueError, TypeError):
                        self.fields["user"].initial = initial_user_id

                initial_season_id = self.initial.get("season")
                if initial_season_id:
                    try:
                        chosen_season = Season.objects.get(pk=initial_season_id)
                    except Season.DoesNotExist:
                        pass
                if chosen_season is None:
                    chosen_season = Season.objects.active()
                    if chosen_season:
                        self.fields["season"].initial = chosen_season.pk
        elif self.instance and self.instance.pk:
            # POST-сезон определён, но экземпляр уже есть — выставляем initial'ы из объекта
            self.fields["user"].initial = self.instance.registration.user_id
            self.fields["season"].initial = self.instance.registration.season_id
            self.fields["stage"].initial = self.instance.stage_id
            self.fields["venue"].initial = self.instance.venue_id
            self.fields["status"].initial = self.instance.status
            self.fields["comment"].initial = self.instance.comment

        # Заполняем queryset этапов и точек для выбранного сезона
        if chosen_season:
            offline_stages = Stage.objects.filter(
                season=chosen_season,
                kind__in=[Stage.Kind.OFFLINE, Stage.Kind.HYBRID],
                is_practice=False,
            ).order_by("order", "starts_at")
            self.fields["stage"].queryset = offline_stages

            # Дефолтный этап: текущий/ближайший или первый
            if not self.fields["stage"].initial:
                default_stage = (
                    Stage.objects.current_or_latest_started(chosen_season, Stage.Kind.OFFLINE)
                    or offline_stages.first()
                )
                if default_stage:
                    self.fields["stage"].initial = default_stage.pk

            # Точки: все площадки сезона
            self.fields["venue"].queryset = Venue.objects.filter(
                seasons=chosen_season
            ).order_by("region", "city", "title")
        else:
            self.fields["stage"].queryset = Stage.objects.none()
            self.fields["venue"].queryset = Venue.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get("user")
        season = cleaned_data.get("season")
        stage = cleaned_data.get("stage")
        venue = cleaned_data.get("venue")

        if season and stage:
            if stage.season_id != season.id:
                self.add_error("stage", f"Этап «{stage.title}» не принадлежит сезону «{season.title}».")
            if not stage.has_offline:
                self.add_error("stage", f"Этап «{stage.title}» не является очным туром.")

        if season and venue:
            if not venue.seasons.filter(pk=season.pk).exists():
                self.add_error("venue", f"Точка «{venue.title}» не заявлена на сезон «{season.title}».")

        if user and stage and venue:
            existing = VenueBooking.objects.filter(
                registration__user=user,
                stage=stage,
                venue=venue,
            ).exclude(status=VenueBooking.Status.CANCELLED)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                user_name = getattr(getattr(user, "profile", None), "full_name", "") or user.email
                self.add_error("user", f"Участник «{user_name}» уже прикреплён к точке «{venue.title}».")

        return cleaned_data

    def save(self, commit=True):
        user = self.cleaned_data["user"]
        season = self.cleaned_data["season"]
        stage = self.cleaned_data["stage"]
        venue = self.cleaned_data["venue"]
        status = self.cleaned_data["status"]
        comment = self.cleaned_data.get("comment", "")

        profile = getattr(user, "profile", None)
        grade = getattr(profile, "grade", None)

        registration, _ = Registration.objects.get_or_create(
            user=user,
            season=season,
            defaults={"grade": grade},
        )
        if grade and not registration.grade:
            registration.grade = grade
            registration.save(update_fields=["grade"])

        if self.instance and self.instance.pk:
            booking = self.instance
            booking.registration = registration
            booking.stage = stage
            booking.venue = venue
            booking.status = status
            booking.comment = comment
        else:
            booking = VenueBooking.objects.filter(registration=registration, stage=stage).first()
            if booking:
                booking.venue = venue
                booking.status = status
                if comment:
                    booking.comment = comment
                self.instance = booking
            else:
                booking = super().save(commit=False)
                booking.registration = registration
                booking.stage = stage
                booking.venue = venue
                booking.status = status
                booking.comment = comment

        if not hasattr(self, "save_m2m"):
            self.save_m2m = getattr(self, "_save_m2m", lambda: None)

        if commit:
            booking.save()
        return booking
