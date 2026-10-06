"""Minimal FHIR R4 mapping: Patient, DiagnosticReport and Observation resources."""

from django.utils import timezone

from accounts.models import User
from medtimeline_eval.markers import MARKERS

from .models import Observation, Report

LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"
_UCUM = {"g/dL": "g/dL", "10^3/uL": "10*3/uL", "10^6/uL": "10*6/uL", "mg/dL": "mg/dL", "mg/L": "mg/L"}
_REPORT_STATUS = {Report.Status.EXTRACTED: "final", Report.Status.NEEDS_REVIEW: "preliminary"}


def _observation(obs: Observation) -> dict:
    marker = MARKERS[obs.marker_code]
    return {
        "resourceType": "Observation",
        "id": f"obs-{obs.pk}",
        "status": "final" if obs.verified else "preliminary",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                    }
                ]
            }
        ],
        "code": {"coding": [{"system": LOINC_SYSTEM, "code": obs.loinc, "display": marker.name}]},
        "subject": {"reference": f"Patient/{obs.patient_id}"},
        "effectiveDateTime": obs.effective_date.isoformat(),
        "valueQuantity": {
            "value": float(obs.canonical_value),
            "unit": obs.canonical_unit,
            "system": UCUM_SYSTEM,
            "code": _UCUM.get(obs.canonical_unit, obs.canonical_unit),
        },
    }


def _diagnostic_report(report: Report, observations: list[Observation]) -> dict:
    resource = {
        "resourceType": "DiagnosticReport",
        "id": f"report-{report.pk}",
        "status": _REPORT_STATUS.get(report.status, "registered"),
        "code": {"text": "Laboratory report"},
        "subject": {"reference": f"Patient/{report.patient_id}"},
        "result": [{"reference": f"Observation/obs-{o.pk}"} for o in observations],
    }
    if report.collected_on:
        resource["effectiveDateTime"] = report.collected_on.isoformat()
    if report.center:
        resource["performer"] = [{"display": report.center.name}]
    return resource


def patient_bundle(patient: User) -> dict:
    """Everything stored about a patient as a FHIR `collection` Bundle."""
    reports = list(Report.objects.filter(patient=patient).select_related("center").prefetch_related("observations"))
    entries = [{"resource": {"resourceType": "Patient", "id": str(patient.pk)}}]
    for report in reports:
        observations = list(report.observations.all())
        entries.append({"resource": _diagnostic_report(report, observations)})
        entries.extend({"resource": _observation(o)} for o in observations)
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": timezone.now().isoformat(),
        "entry": entries,
    }
