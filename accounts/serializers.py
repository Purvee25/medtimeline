from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Consent, User

CONSENT_POLICY_VERSION = "2026-10"


class PatientRegistrationSerializer(serializers.ModelSerializer):
    """Self-registration is patients-only; center staff are created by admins."""

    password = serializers.CharField(write_only=True)
    consent_store_reports = serializers.BooleanField(write_only=True)
    consent_llm_extraction = serializers.BooleanField(write_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "consent_store_reports", "consent_llm_extraction"]

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def validate_consent_store_reports(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError("Consent to store reports is required to use the service.")
        return value

    @transaction.atomic
    def create(self, validated_data: dict) -> User:
        llm_consent = validated_data.pop("consent_llm_extraction")
        validated_data.pop("consent_store_reports")
        user = User.objects.create_user(role=User.Role.PATIENT, **validated_data)
        purposes = [Consent.Purpose.STORE_REPORTS] + ([Consent.Purpose.LLM_EXTRACTION] if llm_consent else [])
        Consent.objects.bulk_create(
            Consent(user=user, purpose=p, policy_version=CONSENT_POLICY_VERSION) for p in purposes
        )
        return user


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Accept email + password instead of username + password.

    simplejwt resolves auth by User.USERNAME_FIELD (= "username").  We intercept
    before the parent runs: look up the user by email, inject their username into
    attrs, then let the parent do the password check and token creation normally.
    """

    # Replace the username field with an email field.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove the username field and add an email field in its place.
        self.fields.pop(User.USERNAME_FIELD, None)
        self.fields["email"] = serializers.EmailField()

    def validate(self, attrs: dict) -> dict:
        email = attrs.pop("email", "").lower()
        try:
            user = User.objects.get(email__iexact=email)
            attrs[User.USERNAME_FIELD] = user.username
        except User.DoesNotExist:
            # Let parent raise the generic "no active account" error.
            attrs[User.USERNAME_FIELD] = ""
        return super().validate(attrs)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "center", "email_verified"]
        read_only_fields = fields
