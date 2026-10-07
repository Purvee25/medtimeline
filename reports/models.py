import uuid

from django.conf import settings
from django.db import models

from accounts.models import Center


class Report(models.Model):
    """An uploaded diagnostic report PDF and its processing state."""

    class Status(models.TextChoices):
        AWAITING_UPLOAD = "awaiting_upload"
        UPLOADED = "uploaded"
        PROCESSING = "processing"
        EXTRACTED = "extracted"
        NEEDS_REVIEW = "needs_review"
        FAILED = "failed"
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    center = models.ForeignKey(Center, null=True, blank=True, on_delete=models.PROTECT, related_name="reports")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    s3_key = models.CharField(max_length=300, unique=True)
    original_filename = models.CharField(max_length=255)
    size_bytes = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AWAITING_UPLOAD)
    collected_on = models.DateField(null=True, blank=True)
    # Raw pipeline output (rows + validation issues) shown to the reviewer; never contains identifiers.
    extraction = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "-created_at"]),
            models.Index(fields=["center", "-created_at"]),
        ]


class Observation(models.Model):
    """One lab value, shaped after FHIR Observation and coded with LOINC."""

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="observations")
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="observations")
    marker_code = models.CharField(max_length=20)
    loinc = models.CharField(max_length=20)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=30)
    canonical_value = models.DecimalField(max_digits=12, decimal_places=4)
    canonical_unit = models.CharField(max_length=30)
    reference_low = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    reference_high = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    effective_date = models.DateField()
    verified = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["report", "marker_code"], name="one_value_per_marker_per_report")
        ]
        # Serves the trend query: one patient, one marker, ordered by date.
        indexes = [models.Index(fields=["patient", "loinc", "effective_date"])]


class AccessLog(models.Model):
    """Append-only audit trail of every access to patient data."""

    class Action(models.TextChoices):
        CREATE = "create"
        VIEW = "view"
        DOWNLOAD = "download"
        LIST = "list"
        REVIEW = "review"
        EXPORT = "export"
        ERASE = "erase"

    # SET_NULL so account erasure keeps a de-identified audit trail instead of blocking deletion.
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    report = models.ForeignKey(Report, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=20, choices=Action.choices)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["patient", "-at"])]


import secrets as _secrets


SHARE_TOKEN_EXPIRY_HOURS = 72


class ReportShareToken(models.Model):
    """Time-limited read-only token so a patient can share a report with their doctor."""

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="share_tokens")
    token = models.CharField(max_length=64, unique=True, default=_secrets.token_urlsafe)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        if not self.pk and not self.expires_at:
            from django.utils import timezone
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(hours=SHARE_TOKEN_EXPIRY_HOURS)
        super().save(*args, **kwargs)

    def is_valid(self) -> bool:
        from django.utils import timezone
        return timezone.now() < self.expires_at
