"""Domain operations on reports: storing extraction output and applying human review."""

import logging
from dataclasses import dataclass
from datetime import date

from django.db import transaction

from accounts.models import User
from medtimeline_eval.markers import MARKERS, is_plausible, normalise_unit, to_canonical

from . import storage
from .models import AccessLog, Observation, Report

logger = logging.getLogger(__name__)


class ReviewError(ValueError):
    """A reviewed value failed validation."""


@dataclass(frozen=True)
class ReviewedValue:
    marker_code: str
    value: float
    unit: str


def _observation(report: Report, code: str, value: float, unit: str, canonical: float, day: date, verified: bool):
    return Observation(
        patient_id=report.patient_id,
        report=report,
        marker_code=code,
        loinc=MARKERS[code].loinc,
        value=value,
        unit=unit,
        canonical_value=canonical,
        canonical_unit=MARKERS[code].canonical_unit,
        effective_date=day,
        verified=verified,
    )


@transaction.atomic
def save_extraction(report: Report, result: dict) -> None:
    """Persist pipeline output. Only clean rows become observations; the rest wait for review."""
    report.extraction = result
    report.collected_on = date.fromisoformat(result["collected_on"]) if result.get("collected_on") else None
    report.status = result["status"]
    report.error = result.get("error", "")
    report.save(update_fields=["extraction", "collected_on", "status", "error", "updated_at"])

    report.observations.filter(verified=False).delete()
    if report.collected_on is None:
        return
    Observation.objects.bulk_create(
        _observation(report, r["marker"], r["value"], r["unit"], r["canonical_value"], report.collected_on, False)
        for r in result["results"]
        if not r["issues"]
    )


def _validate_reviewed(row: ReviewedValue) -> float:
    if row.marker_code not in MARKERS:
        raise ReviewError(f"Unknown marker {row.marker_code!r}")
    try:
        canonical = to_canonical(row.marker_code, row.value, row.unit)
    except ValueError as exc:
        raise ReviewError(str(exc)) from exc
    if not is_plausible(row.marker_code, canonical):
        raise ReviewError(f"{row.marker_code}={row.value} {row.unit} is outside the plausible range")
    return round(canonical, 4)


@transaction.atomic
def apply_review(report: Report, collected_on: date, rows: list[ReviewedValue]) -> None:
    """Replace the report's observations with human-verified values.

    Raises:
        ReviewError: A value is unknown, has the wrong unit, is implausible, or is duplicated.
    """
    codes = [r.marker_code for r in rows]
    if len(codes) != len(set(codes)):
        raise ReviewError("Each marker may appear only once per report")
    validated = [(r, _validate_reviewed(r)) for r in rows]

    report.observations.all().delete()
    Observation.objects.bulk_create(
        _observation(report, r.marker_code, r.value, normalise_unit(r.unit), canonical, collected_on, True)
        for r, canonical in validated
    )
    report.collected_on = collected_on
    report.status = Report.Status.EXTRACTED
    report.save(update_fields=["collected_on", "status", "updated_at"])


def erase_patient(patient: User) -> int:
    """Delete a patient's files and account (right to erasure). Returns the number of reports removed.

    Files go first: if storage fails the account survives and the request can be retried, rather than
    leaving orphaned health data in S3 with no owner. The audit log keeps de-identified rows.
    """
    keys = list(Report.objects.filter(patient=patient).values_list("s3_key", flat=True))
    for key in keys:
        storage.delete(key)
    with transaction.atomic():
        AccessLog.objects.create(actor=patient, patient=patient, action=AccessLog.Action.ERASE)
        # Reports go first: Report.uploaded_by is PROTECT, which also blocks a self-uploader's deletion.
        Report.objects.filter(patient=patient).delete()
        patient.delete()
    logger.info("Patient erased", extra={"reports": len(keys)})
    return len(keys)
