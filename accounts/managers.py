from django.contrib.auth.base_user import BaseUserManager


class AccountManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, display_name: str, **extra_fields):
        if not display_name or not display_name.strip():
            raise ValueError("display_name must not be blank")
        account = self.model(display_name=display_name.strip(), **extra_fields)
        account.set_unusable_password()
        account.save(using=self._db)
        return account

    def create_superuser(self, display_name: str, **extra_fields):
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_admin", True)
        if extra_fields.get("is_admin") is not True:
            raise ValueError("A superuser must have is_admin=True")
        return self.create_user(display_name=display_name, **extra_fields)
