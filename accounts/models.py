import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models

from .managers import AccountManager


class Account(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AccountManager()

    USERNAME_FIELD = "id"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        db_table = "account"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(display_name__regex=r"^\s*$"),
                name="account_display_name_nonblank",
            ),
            models.CheckConstraint(
                condition=models.Q(password__startswith="!"),
                name="account_password_unusable",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.password or not self.password.startswith("!"):
            self.set_unusable_password()
        super().save(*args, **kwargs)

    @property
    def is_staff(self) -> bool:
        return self.is_admin

    def has_perm(self, perm, obj=None) -> bool:
        return self.is_active and self.is_admin

    def has_module_perms(self, app_label) -> bool:
        return self.is_active and self.is_admin

    def __str__(self) -> str:
        return self.display_name


class ExternalIdentity(models.Model):
    class Provider(models.TextChoices):
        GITHUB = "github", "GitHub"
        ORCID = "orcid", "ORCID"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="external_identities",
    )
    provider = models.CharField(max_length=10, choices=Provider)
    provider_subject = models.TextField()
    public_identifier = models.TextField()
    profile_url = models.URLField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    last_authenticated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "external_identity"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(provider__in=["github", "orcid"]),
                name="external_identity_provider_valid",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_subject"],
                name="external_identity_provider_subject_uniq",
            ),
            models.UniqueConstraint(
                fields=["account", "provider"],
                name="external_identity_account_provider_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_provider_display()}: {self.public_identifier}"


class PersonalApiToken(models.Model):
    """Revocable personal bearer credential; the secret is never retained."""

    class Scope(models.TextChoices):
        CIRCUITS_SUBMIT = "circuits:submit", "Submit circuits"
        COLLECTIONS_WRITE = "collections:write", "Manage circuit collections"
        TAGS_WRITE = "tags:write", "Manage community tags"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="personal_api_tokens",
    )
    public_id = models.CharField(max_length=24, unique=True)
    secret_digest = models.CharField(max_length=64)
    display_prefix = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_api_token"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(secret_digest__regex=r"^[0-9a-f]{64}$"),
                name="personal_api_token_digest_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(name__regex=r"^\s*$"),
                name="personal_api_token_name_nonblank",
            ),
        ]
        indexes = [
            models.Index(
                fields=["account", "-created_at"],
                name="idx_api_token_account_created",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.display_prefix}…)"
