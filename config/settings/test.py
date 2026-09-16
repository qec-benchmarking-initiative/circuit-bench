from .base import *  # noqa: F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Legacy regression fixtures intentionally retain their original release.
# Versioned-contract tests override this mapping and install real contracts.
CURRENT_SUBMISSION_SCHEMAS = dict.fromkeys(
    ["decoder", "circuit", "result", "machine", "noise_model", "tag", "benchmark", "evaluator"],
    "0.1",
)
