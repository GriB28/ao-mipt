from django.db import models


class TimeStampedModel(models.Model):
    """Базовый класс: у всех сущностей есть даты создания и изменения."""

    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        abstract = True
