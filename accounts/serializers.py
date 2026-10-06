from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

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


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "center"]
        read_only_fields = fields
