from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Общее"

    def ready(self):
        from apps.core.plural import patch_admin_interface_declensions
        patch_admin_interface_declensions()
