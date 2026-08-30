from django.contrib import admin

from .models import Account, ExternalIdentity


class ExternalIdentityInline(admin.TabularInline):
    model = ExternalIdentity
    extra = 0
    readonly_fields = ("provider_subject", "created_at", "last_authenticated_at")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("display_name", "id", "is_active", "is_admin", "created_at")
    list_filter = ("is_active", "is_admin")
    search_fields = ("display_name",)
    readonly_fields = ("id", "password", "last_login", "created_at", "updated_at")
    inlines = (ExternalIdentityInline,)


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("public_identifier", "provider", "account", "created_at")
    list_filter = ("provider",)
    search_fields = ("public_identifier", "provider_subject", "account__display_name")

