from datetime import date

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from accounts.models import Consent, User
from medtimeline_eval.markers import MARKERS

from .models import Observation, Report


class ReportSerializer(serializers.ModelSerializer):
    patient = serializers.SlugRelatedField(slug_field="username", read_only=True)
    center = serializers.StringRelatedField()

    class Meta:
        model = Report
        fields = [
            "id",
            "patient",
            "center",
            "original_filename",
            "size_bytes",
            "status",
            "collected_on",
            "error",
            "created_at",
        ]
        read_only_fields = fields


PATIENT_UNAVAILABLE = "No patient with that username has consented to report storage."
EARLIEST_COLLECTION_DATE = date(1900, 1, 1)


class ReportCreateSerializer(serializers.Serializer):
    """Upload request. Staff must name the patient; patients always upload for themselves."""

    original_filename = serializers.CharField(max_length=255)
    size_bytes = serializers.IntegerField(min_value=1)
    patient = serializers.CharField(max_length=150, required=False)

    def validate_original_filename(self, value: str) -> str:
        if not value.lower().endswith(".pdf"):
            raise serializers.ValidationError("Only PDF reports are accepted.")
        return value

    def validate_size_bytes(self, value: int) -> int:
        if value > settings.MAX_REPORT_BYTES:
            raise serializers.ValidationError(f"File exceeds {settings.MAX_REPORT_BYTES} bytes.")
        return value

    def validate(self, attrs: dict) -> dict:
        user = self.context["request"].user
        if user.is_center_staff and "patient" not in attrs:
            raise serializers.ValidationError({"patient": "Center staff must specify the patient."})
        if user.is_patient:
            attrs["patient"] = user
            return attrs
        # Same error whether the username is unknown or the patient hasn't consented, so the
        # endpoint can't be used to discover which usernames exist.
        patient = User.objects.filter(
            username=attrs["patient"],
            role=User.Role.PATIENT,
            consents__purpose=Consent.Purpose.STORE_REPORTS,
            consents__withdrawn_at__isnull=True,
        ).first()
        if patient is None:
            raise serializers.ValidationError({"patient": PATIENT_UNAVAILABLE})
        attrs["patient"] = patient
        return attrs


class ObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Observation
        fields = [
            "id",
            "marker_code",
            "loinc",
            "value",
            "unit",
            "canonical_value",
            "canonical_unit",
            "effective_date",
            "verified",
        ]
        read_only_fields = fields


class ReviewedValueSerializer(serializers.Serializer):
    marker_code = serializers.ChoiceField(choices=list(MARKERS))
    value = serializers.FloatField()
    unit = serializers.CharField(max_length=30)


class ReviewSerializer(serializers.Serializer):
    collected_on = serializers.DateField()
    observations = ReviewedValueSerializer(many=True, allow_empty=False)

    def validate_collected_on(self, value: date) -> date:
        if value > timezone.localdate():
            raise serializers.ValidationError("Collection date can't be in the future.")
        if value < EARLIEST_COLLECTION_DATE:
            raise serializers.ValidationError("Collection date is implausibly old.")
        return value
