from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:
        # Register the deliberately small bridge between allauth's private
        # OAuth bookkeeping and DecoderBench's public identity records.
        from . import signals  # noqa: F401
