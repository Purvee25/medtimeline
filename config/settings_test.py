"""Test settings: deterministic, no external services."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-with-enough-length-for-hs256")

from .settings import *

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}
