from django import forms

from apps.accounts.forms import ContactRequiredMixin
from apps.accounts.regions import REGION_CHOICES

from .models import Venue


class VenueForm(ContactRequiredMixin, forms.ModelForm):
    """
    Заявка на площадку и её последующая правка.

    Контакт площадки — телефон или телеграм, хотя бы один: школьнику и его
    родителям нужно уметь быстро дозвониться, а чем пользуется
    ответственный, решает он сам.
    """

    CONTACT_FIELDS = ("contact_phone", "contact_telegram")
    CONTACT_ERROR = "Укажите телефон или Telegram — хотя бы один способ связи."

    region = forms.ChoiceField(label="Регион", choices=REGION_CHOICES)

    class Meta:
        model = Venue
        fields = [
            "title", "region", "city", "address", "latitude", "longitude",
            "description", "contact_name", "contact_phone", "contact_telegram",
            "contact_email",
        ]
        widgets = {
            # Координаты заполняет карта на странице, поля скрыты от глаз.
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
            "description": forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "Как пройти, какой вход, что взять с собой, во сколько собираемся",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Регион, записанный до появления списка, мог в него не попасть —
        # не ломаем правку старой площадки из-за этого.
        # Контакты площадки публичные — школьники звонят по ним в день тура.
        # Человек должен знать это до того, как впишет личный номер.
        for name in ("contact_name", "contact_phone", "contact_telegram", "contact_email"):
            hint = self.fields[name].help_text
            self.fields[name].help_text = f"{hint}. Видно всем на странице площадки" if hint \
                else "Видно всем на странице площадки"
        current = self.instance.region if self.instance and self.instance.pk else ""
        if current and current not in dict(REGION_CHOICES):
            self.fields["region"].choices = list(REGION_CHOICES) + [(current, current)]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("latitude") is None or cleaned.get("longitude") is None:
            raise forms.ValidationError("Отметьте площадку на карте — без точки её не найдут.")
        return cleaned


class VenueMailForm(forms.Form):
    """Письмо участникам своей площадки."""

    subject = forms.CharField(label="Тема", max_length=250)
    body = forms.CharField(
        label="Текст письма",
        widget=forms.Textarea(attrs={
            "rows": 10,
            "placeholder": "Здравствуйте, {{ first_name }}!\n\n"
                           "Напоминаем: тур пройдёт 22 октября, сбор в 9:30 у главного входа.",
        }),
        help_text="Можно использовать {{ first_name }} и {{ last_name }} — подставится имя получателя.",
    )
