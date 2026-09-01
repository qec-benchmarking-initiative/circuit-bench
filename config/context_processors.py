from django.conf import settings


def deployment(_request):
    environment = settings.DEPLOYMENT_ENVIRONMENT
    return {
        "deployment_environment": environment,
        "deployment_git_commit_short": settings.DEPLOYMENT_GIT_COMMIT[:7],
        "deployment_git_message": settings.DEPLOYMENT_GIT_MESSAGE,
        "is_staging": environment == "staging",
    }
