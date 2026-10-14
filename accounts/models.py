import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

EMAIL_VERIFY_EXPIRY_HOURS = 24


class Center(models.Model):
    """A diagnostic center whose staff upload reports for patients."""

    name = models.CharField(max_length=200, unique=True)

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Platform user. Role decides which reports they can reach."""

    class Role(models.TextChoices):
        PATIENT = "patient"
        CENTER_STAFF = "center_staff"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)
    center = models.ForeignKey(Center, null=True, blank=True, on_delete=models.PROTECT, related_name="staff")
    # Email is required and unique so patients can log in with it.
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)

    REQUIRED_FIELDS = ["email"]

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="staff_has_center_patient_has_none",
                condition=(
                    models.Q(role="center_staff", center__isnull=False) | models.Q(role="patient", center__isnull=True)
                ),
            )
        ]

    @property
    def is_patient(self) -> bool:
        return self.role == self.Role.PATIENT

    @property
    def is_center_staff(self) -> bool:
        return self.role == self.Role.CENTER_STAFF


class Consent(models.Model):
    """Record of what a patient agreed to and when; withdrawn_at set on withdrawal."""

    class Purpose(models.TextChoices):
        STORE_REPORTS = "store_reports"
        LLM_EXTRACTION = "llm_extraction"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    policy_version = models.CharField(max_length=20)
    granted_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose"])]


class EmailVerificationToken(models.Model):
    """Single-use token e-mailed to a patient on registration to verify their address."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="email_verification")
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self) -> bool:
        return timezone.now() < self.created_at + timedelta(hours=EMAIL_VERIFY_EXPIRY_HOURS)
