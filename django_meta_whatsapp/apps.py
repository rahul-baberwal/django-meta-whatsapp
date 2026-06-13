from django.apps import AppConfig


class DjangoMetaWhatsappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_meta_whatsapp"
    verbose_name = "Meta WhatsApp"

    def ready(self):
        import django_meta_whatsapp.signals  # noqa
