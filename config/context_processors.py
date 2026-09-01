from django.conf import settings


def deployment(_request):
    environment = settings.DEPLOYMENT_ENVIRONMENT
    return {
        "deployment_environment": environment,
        "is_staging": environment == "staging",
    }
