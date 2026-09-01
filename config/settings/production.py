import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if SECRET_KEY == "decoderbench-development-only":  # noqa: F405
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production")

DEBUG = False
MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if render_hostname:
    render_origin = f"https://{render_hostname}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
