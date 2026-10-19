"""
Формы ручной записи участника на точку проведения очного тура.
"""

from django import forms

from apps.accounts.models import User
from apps.seasons.models import Season, Stage
from apps.venues.models import Venue

from .models import Registration, VenueBooking


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        profile = getattr(obj, "profile", None)
        full_name = profile.full_name if profile else ""
        if full_name:
            grade_str = f", {profile.grade} кл." if profile.grade else ""
            return f"{full_name} ({obj.email}{grade_str})"
        return obj.email


class SeasonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        active_tag = " ★ (текущий сезон)" if obj.is_active else ""
        return f"{obj.title} ({obj.years_label}){active_tag}"


class StageChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.season.title} — {obj.title}"


class VenueChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.title} ({obj.city}, {obj.address})"


class VenueBookingAdminForm(forms.ModelForm):
    """
    Удобная форма ручной записи участника на точку проведения очного этапа.

    Позволяет администратору:
    1. Найти участника по email или ФИО через фильтр.
    2. Выбрать сезон проведения.
    3. Выбрать очный этап сезона (если их несколько).
    4. Выбрать точку проведения из выпадающего списка точек этого сезона.
    """

    filter_type = forms.ChoiceField(
        choices=[
            ("all", "Все (почта или ФИО)"),
            ("email", "Только по почте"),
            ("name", "Только по ФИО"),
        ],
        required=False,
        initial="all",
        label="Фильтр поиска",
    )
    user = UserChoiceField(
        queryset=User.objects.select_related("profile").all(),
        required=True,
        label="Участник",
        help_text="Выберите участника с помощью поиска выше (по email или ФИО).",
    )
    season = SeasonChoiceField(
        queryset=Season.objects.all().order_by("-year"),
        required=True,
        label="Сезон",
        help_text="Сезон проведения олимпиады.",
    )
    stage = StageChoiceField(
        queryset=Stage.objects.filter(kind__in=[Stage.Kind.OFFLINE, Stage.Kind.HYBRID], is_practice=False),
        required=True,
        label="Очный этап",
        help_text="Очный этап выбранного сезона.",
    )
    venue = VenueChoiceField(
        queryset=Venue.objects.all().order_by("region", "city", "title"),
        required=True,
        label="Точка проведения",
        help_text="Точка проведения очного этапа для выбранного сезона.",
    )
    status = forms.ChoiceField(
        choices=VenueBooking.Status.choices,
        initial=VenueBooking.Status.BOOKED,
        label="Статус записи",
    )
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
        label="Комментарий к записи",
    )

    class Meta:
        model = VenueBooking
        fields = ("stage", "venue", "status", "comment")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["filter_type", "user", "season", "stage", "venue", "status", "comment"])

        if self.instance and self.instance.pk:
            self.fields["user"].initial = self.instance.registration.user_id
            self.fields["season"].initial = self.instance.registration.season_id
            self.fields["stage"].initial = self.instance.stage_id
            self.fields["venue"].initial = self.instance.venue_id
            self.fields["status"].initial = self.instance.status
            self.fields["comment"].initial = self.instance.comment
        else:
            # Handle initial values passed from GET or kwargs
            active_season = Season.objects.active()
            if not self.initial.get("season") and active_season:
                self.fields["season"].initial = active_season.pk

            chosen_season_id = self.initial.get("season") or (active_season.pk if active_season else None)
            if chosen_season_id:
                try:
                    chosen_season = Season.objects.get(pk=chosen_season_id)
                except Season.DoesNotExist:
                    chosen_season = active_season

                if chosen_season and not self.initial.get("stage"):
                    default_stage = (
                        Stage.objects.current_or_next(chosen_season, Stage.Kind.OFFLINE)
                        or Stage.objects.filter(
                            season=chosen_season,
                            kind__in=[Stage.Kind.OFFLINE, Stage.Kind.HYBRID],
                            is_practice=False,
                        ).first()
                    )
                    if default_stage:
                        self.fields["stage"].initial = default_stage.pk

            if self.initial.get("venue"):
                venue_id = self.initial.get("venue")
                try:
                    v = Venue.objects.get(pk=venue_id)
                    v_season = v.seasons.filter(is_active=True).first() or v.seasons.first()
                    if v_season and not self.initial.get("season"):
                        self.fields["season"].initial = v_season.pk
                except Venue.DoesNotExist:
                    pass

    def clean(self):
        cleaned_data = super().clean()
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
            else:
                booking = super().save(commit=False)
                booking.registration = registration
                booking.stage = stage
                booking.venue = venue
                booking.status = status
                booking.comment = comment

        if commit:
            booking.save()
        return booking
