"""Trend and FHIR export endpoints over a patient's observations."""

from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from medtimeline_eval.markers import MARKERS

from .fhir import patient_bundle
from .models import AccessLog, Observation, Report


def resolve_patient(request: Request, username: str | None) -> User:
    """Patients may only query themselves; staff may query patients with a report at their center.

    Staff results are further limited to their own center's observations (see TrendView), so creating
    a report for a patient never exposes what other centers or the patient themselves uploaded.

    Out-of-scope patients raise 404, matching the report endpoints.
    """
    user: User = request.user
    if user.is_patient:
        return user
    if not username:
        raise serializers.ValidationError({"patient": "Center staff must specify the patient."})
    patient = User.objects.filter(username=username, role=User.Role.PATIENT).first()
    if patient is None or not Report.objects.filter(patient=patient, center_id=user.center_id).exists():
        raise NotFound()
    return patient


class TrendQuerySerializer(serializers.Serializer):
    marker = serializers.ChoiceField(choices=list(MARKERS))
    patient = serializers.CharField(required=False)
    verified_only = serializers.BooleanField(default=False)


class TrendView(APIView):
    """GET /api/trends/?marker=crp — one marker over time, across every center, in canonical units."""

    def get(self, request: Request) -> Response:
        query = TrendQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        patient = resolve_patient(request, query.validated_data.get("patient"))

        marker = MARKERS[query.validated_data["marker"]]
        observations = Observation.objects.filter(patient=patient, loinc=marker.loinc)
        if request.user.is_center_staff:
            observations = observations.filter(report__center_id=request.user.center_id)
        if query.validated_data["verified_only"]:
            observations = observations.filter(verified=True)
        points = observations.order_by("effective_date").values(
            "effective_date", "canonical_value", "verified", "report_id", "report__center__name"
        )
        AccessLog.objects.create(actor=request.user, patient=patient, action=AccessLog.Action.VIEW)
        return Response(
            {
                "marker": marker.code,
                "name": marker.name,
                "loinc": marker.loinc,
                "unit": marker.canonical_unit,
                "reference_range": {"low": marker.normal_range[0], "high": marker.normal_range[1], "approximate": True},
                "points": [
                    {
                        "date": p["effective_date"],
                        "value": float(p["canonical_value"]),
                        "verified": p["verified"],
                        "report_id": p["report_id"],
                        "center": p["report__center__name"],
                    }
                    for p in points
                ],
            }
        )


class MarkerListView(APIView):
    """GET /api/markers/ — the marker catalogue, so clients never keep their own copy."""

    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "code": m.code,
                    "name": m.name,
                    "loinc": m.loinc,
                    "unit": m.canonical_unit,
                    "units": [m.canonical_unit, *m.alt_units],
                }
                for m in MARKERS.values()
            ]
        )


class FhirExportView(APIView):
    """GET /api/fhir/Patient/$everything — the caller's own data as a FHIR R4 Bundle (data portability)."""

    def get(self, request: Request) -> Response:
        if not request.user.is_patient:
            return Response({"detail": "Only patients can export their own record."}, status=status.HTTP_403_FORBIDDEN)
        AccessLog.objects.create(actor=request.user, patient=request.user, action=AccessLog.Action.EXPORT)
        return Response(patient_bundle(request.user), content_type="application/fhir+json")
