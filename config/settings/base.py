import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "decoderbench-development-only")
DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.orcid",
    "accounts.apps.AccountsConfig",
    "registry.apps.RegistryConfig",
    "pages.apps.PagesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=(
            "postgresql://decoderbench:decoderbench_dev@127.0.0.1:5432/"
            "decoderbench"
        ),
        conn_max_age=0,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = []
AUTH_USER_MODEL = "accounts.Account"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SITE_ID = 1

ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = None
ACCOUNT_LOGIN_METHODS = set()
ACCOUNT_SIGNUP_FIELDS = ["display_name*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_ONLY = True
SOCIALACCOUNT_ADAPTER = "accounts.adapters.DecoderBenchSocialAccountAdapter"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_REQUIRED = False
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_QUERY_EMAIL = False
SOCIALACCOUNT_STORE_TOKENS = False
SOCIALACCOUNT_LOGIN_ON_GET = False

# Social-only accounts intentionally have profile fields but no local login
# methods. allauth reports that deliberate combination as a warning.
SILENCED_SYSTEM_CHECKS = ["account.W001"]

SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "APPS": [
            {
                "client_id": os.environ.get("GITHUB_CLIENT_ID", ""),
                "secret": os.environ.get("GITHUB_CLIENT_SECRET", ""),
                "key": "",
            }
        ],
    },
    "orcid": {
        "APPS": [
            {
                "client_id": os.environ.get("ORCID_CLIENT_ID", ""),
                "secret": os.environ.get("ORCID_CLIENT_SECRET", ""),
                "key": "",
            }
        ],
        "BASE_DOMAIN": os.environ.get("ORCID_BASE_DOMAIN", "orcid.org"),
        "MEMBER_API": False,
    },
}

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
