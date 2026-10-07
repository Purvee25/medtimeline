"""Extraction task, review, trends, FHIR export, consent and erasure."""

import random
from datetime import date

import anthropic
import httpx2 as httpx
import pytest
from celery.exceptions import Retry
from django.conf import settings

from accounts.models import Center, Consent, User
from medtimeline_eval.generate import generate_report
from medtimeline_extract.llm import ExtractedResult, Extraction
from reports import tasks
from reports.models import AccessLog, Observation, Report
from reports.tasks import extract_report
from tests.helpers import _as, _create_report, _patient, _staff

pytestmark = pytest.mark.django_db
COLLECTED = date(2025, 3, 1)


def _row(marker: str, value: float, unit: str) -> ExtractedResult:
    return ExtractedResult(marker=marker, printed_name=marker, value=value, unit=unit)


@pytest.fixture
def fake_claude(monkeypatch):
    """Replace the Claude call; set `.results` / `.collected_on` / `.error` per test."""

    class Fake:
        results = [_row("crp", 4.4, "mg/L"), _row("hb", 13.1, "g/dL")]
        collected_on = COLLECTED
        error: Exception | None = None
        calls = 0

        def __call__(self, text, client):
            self.calls += 1
            if self.error:
                raise self.error
            return Extraction(collected_on=self.collected_on, results=self.results)

    fake = Fake()
    monkeypatch.setattr("medtimeline_extract.pipeline.extract_results", fake)
    monkeypatch.setattr(tasks.anthropic, "Anthropic", lambda: None)
    return fake


def _uploaded_report(s3, tmp_path, patient: User, **extra) -> Report:
    generate_report("r", "table_classic", random.Random(1), tmp_path)
    data = _create_report(patient, **extra)
    s3.put_object(
        Bucket=settings.REPORTS_BUCKET, Key=data["upload"]["fields"]["key"], Body=(tmp_path / "r.pdf").read_bytes()
    )
    report = Report.objects.get(pk=data["report"]["id"])
    report.status = Report.Status.UPLOADED
    report.save()
    return report


# --- extraction task ------------------------------------------------------


def test_clean_extraction_stores_observations(s3, tmp_path, fake_claude):
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))
    assert extract_report(str(report.pk)) == Report.Status.EXTRACTED

    report.refresh_from_db()
    assert report.collected_on == COLLECTED
    obs = {o.marker_code: o for o in report.observations.all()}
    assert set(obs) == {"crp", "hb"}
    assert obs["crp"].loinc == "1988-5" and not obs["crp"].verified


def test_suspicious_rows_are_held_back_for_review(s3, tmp_path, fake_claude):
    fake_claude.results = [_row("hb", 131.0, "g/dL"), _row("crp", 4.4, "mg/L")]
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))
    assert extract_report(str(report.pk)) == Report.Status.NEEDS_REVIEW
    assert list(report.observations.values_list("marker_code", flat=True)) == ["crp"]


def test_missing_collection_date_stores_nothing(s3, tmp_path, fake_claude):
    fake_claude.collected_on = None
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))
    assert extract_report(str(report.pk)) == Report.Status.NEEDS_REVIEW
    assert not report.observations.exists()


def test_no_llm_consent_skips_claude(s3, tmp_path, fake_claude):
    report = _uploaded_report(s3, tmp_path, _patient("alice"))
    assert extract_report(str(report.pk)) == Report.Status.NEEDS_REVIEW
    assert fake_claude.calls == 0
    report.refresh_from_db()
    assert report.extraction["skipped"] == "no_llm_consent"


def test_task_is_idempotent(s3, tmp_path, fake_claude):
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))
    extract_report(str(report.pk))
    assert extract_report(str(report.pk)) is None
    assert fake_claude.calls == 1


def test_permanent_error_marks_failed(s3, tmp_path, fake_claude):
    fake_claude.error = ValueError("bad output")
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))
    assert extract_report(str(report.pk)) == Report.Status.FAILED
    report.refresh_from_db()
    assert "bad output" in report.error


def test_transient_error_retries_then_fails_on_last_attempt(s3, tmp_path, fake_claude):
    fake_claude.error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))

    with pytest.raises(Retry):
        extract_report.apply(args=[str(report.pk)])
    report.refresh_from_db()
    assert report.status == Report.Status.PROCESSING

    extract_report.apply(args=[str(report.pk)], retries=tasks.MAX_RETRIES)
    report.refresh_from_db()
    assert report.status == Report.Status.FAILED and "after 3 retries" in report.error


# --- review ---------------------------------------------------------------


def _review(user, report, observations, collected_on="2025-03-01"):
    return _as(user).post(
        f"/api/reports/{report.pk}/review/",
        {"collected_on": collected_on, "observations": observations},
        format="json",
    )


def test_review_replaces_values_and_verifies(s3, tmp_path, fake_claude):
    alice = _patient("alice", llm_consent=True)
    report = _uploaded_report(s3, tmp_path, alice)
    extract_report(str(report.pk))

    response = _review(alice, report, [{"marker_code": "chol", "value": 5.17, "unit": "mmol/L"}])
    assert response.status_code == 200
    (obs,) = report.observations.all()
    assert obs.verified and obs.marker_code == "chol" and float(obs.canonical_value) == pytest.approx(200, rel=0.01)
    assert AccessLog.objects.filter(action="review").count() == 1


@pytest.mark.parametrize(
    "observations",
    [
        [{"marker_code": "hb", "value": 131, "unit": "g/dL"}],
        [{"marker_code": "hb", "value": 13, "unit": "mmol/L"}],
        [{"marker_code": "hb", "value": 13, "unit": "g/dL"}, {"marker_code": "hb", "value": 14, "unit": "g/dL"}],
        [],
    ],
)
def test_review_rejects_invalid_values(s3, tmp_path, fake_claude, observations):
    alice = _patient("alice", llm_consent=True)
    report = _uploaded_report(s3, tmp_path, alice)
    extract_report(str(report.pk))
    assert _review(alice, report, observations).status_code == 400
    assert report.observations.count() == 2


def test_review_blocked_before_extraction_and_for_other_patients(s3, tmp_path):
    alice, bob = _patient("alice"), _patient("bob")
    report = _uploaded_report(s3, tmp_path, alice)
    row = [{"marker_code": "hb", "value": 13, "unit": "g/dL"}]
    assert _review(alice, report, row).status_code == 409
    assert _review(bob, report, row).status_code == 404


# --- trends ---------------------------------------------------------------


def _observe(patient, report, code, value, day, verified=True):
    from medtimeline_eval.markers import MARKERS

    Observation.objects.create(
        patient=patient,
        report=report,
        marker_code=code,
        loinc=MARKERS[code].loinc,
        value=value,
        unit=MARKERS[code].canonical_unit,
        canonical_value=value,
        canonical_unit=MARKERS[code].canonical_unit,
        effective_date=day,
        verified=verified,
    )


def test_trend_merges_centers_in_date_order_and_scopes_access():
    alice, bob = _patient("alice"), _patient("bob")
    center_a, center_b = Center.objects.create(name="A"), Center.objects.create(name="B")
    staff_a, staff_b = _staff("sa", center_a), _staff("sb", center_b)
    r1 = Report.objects.get(pk=_create_report(staff_a, patient="alice")["report"]["id"])
    r2 = Report.objects.get(pk=_create_report(staff_b, patient="alice")["report"]["id"])
    _observe(alice, r2, "crp", 9.0, date(2025, 5, 1))
    _observe(alice, r1, "crp", 3.0, date(2025, 1, 1), verified=False)

    data = _as(alice).get("/api/trends/?marker=crp").data
    assert [p["value"] for p in data["points"]] == [3.0, 9.0]
    assert [p["center"] for p in data["points"]] == ["A", "B"]
    assert data["loinc"] == "1988-5" and data["reference_range"]["approximate"]
    assert len(_as(alice).get("/api/trends/?marker=crp&verified_only=true").data["points"]) == 1

    assert _as(bob).get("/api/trends/?marker=crp").data["points"] == []
    assert _as(staff_a).get("/api/trends/?marker=crp&patient=alice").status_code == 200
    assert _as(staff_a).get("/api/trends/?marker=crp&patient=bob").status_code == 404
    assert _as(staff_a).get("/api/trends/?marker=crp").status_code == 400
    assert _as(alice).get("/api/trends/?marker=nope").status_code == 400


# --- FHIR export, consent, erasure ------------------------------------------


def test_fhir_export_contains_only_own_records():
    alice, bob = _patient("alice"), _patient("bob")
    report = Report.objects.get(pk=_create_report(alice)["report"]["id"])
    _observe(alice, report, "hb", 13.5, date(2025, 2, 2))
    _create_report(bob)

    bundle = _as(alice).get("/api/fhir/Patient/$everything").json()
    types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert bundle["resourceType"] == "Bundle" and types == ["Patient", "DiagnosticReport", "Observation"]
    obs = bundle["entry"][2]["resource"]
    assert obs["code"]["coding"][0] == {"system": "http://loinc.org", "code": "718-7", "display": "Hemoglobin"}
    assert obs["valueQuantity"]["value"] == 13.5 and obs["status"] == "final"
    assert _as(_staff("s", Center.objects.create(name="A"))).get("/api/fhir/Patient/$everything").status_code == 403


def test_consent_withdraw_and_regrant():
    alice = _patient("alice", llm_consent=True)
    client = _as(alice)
    client.post("/api/auth/consents/", {"purpose": "llm_extraction", "granted": False}, format="json")
    assert not alice.consents.filter(purpose=Consent.Purpose.LLM_EXTRACTION, withdrawn_at__isnull=True).exists()
    client.post("/api/auth/consents/", {"purpose": "llm_extraction", "granted": True}, format="json")
    assert alice.consents.filter(purpose=Consent.Purpose.LLM_EXTRACTION, withdrawn_at__isnull=True).count() == 1
    assert client.post("/api/auth/consents/", {"purpose": "x", "granted": True}, format="json").status_code == 400


def test_erasure_deletes_account_reports_and_files(s3, tmp_path):
    alice = _patient("alice")
    _uploaded_report(s3, tmp_path, alice)
    assert s3.list_objects_v2(Bucket=settings.REPORTS_BUCKET)["KeyCount"] == 1

    assert _as(alice).delete("/api/auth/me/").status_code == 204
    assert not User.objects.filter(username="alice").exists()
    assert not Report.objects.exists()
    assert s3.list_objects_v2(Bucket=settings.REPORTS_BUCKET)["KeyCount"] == 0
    assert AccessLog.objects.filter(action="erase", actor__isnull=True).count() == 1


def test_staff_cannot_self_erase():
    assert _as(_staff("s", Center.objects.create(name="A"))).delete("/api/auth/me/").status_code == 403


def test_marker_catalogue_endpoint():
    data = _as(_patient("alice")).get("/api/markers/").data
    chol = next(m for m in data if m["code"] == "chol")
    assert chol == {
        "code": "chol",
        "name": "Total Cholesterol",
        "loinc": "2093-3",
        "unit": "mg/dL",
        "units": ["mg/dL", "mmol/L"],
    }


def test_presigned_urls_use_public_endpoint_when_configured(settings):
    from reports import storage

    settings.S3_PUBLIC_ENDPOINT_URL = "http://localhost:5000"
    storage._presign_client.cache_clear()
    upload = _create_report(_patient("alice"))["upload"]
    assert upload["url"].startswith("http://localhost:5000/")
    storage._presign_client.cache_clear()
