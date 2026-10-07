from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from .health import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path(settings.ADMIN_PATH, admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("reports.urls")),
]
