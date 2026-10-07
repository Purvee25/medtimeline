"""Regression tests for issues found in the multi-agent audit (access control, races, validation)."""

import threading
import time
from datetime import date, timedelta

import pytest
from django.conf import settings
from django.db import connection
from rest_framework.test import APIClient

from accounts.models import Center
from reports import storage, tasks, views
from reports.models import AccessLog, Observation, Report
from tests.helpers import PASSWORD, _as, _create_report, _patient, _staff
from tests.test_workflow import _observe, _uploaded_report

pytestmark = pytest.mark.django_db
RACE_WINDOW_S = 0.3


def test_staff_upload_does_not_unlock_other_centers_data():
    alice = _patient("alice")
    center_a, center_b = Center.objects.create(name="A"), Center.objects.create(name="B")
    staff_a, staff_b = _staff("sa", center_a), _staff("sb", center_b)
    own = Report.objects.get(pk=_create_report(alice)["report"]["id"])
    at_a = Report.objects.get(pk=_create_report(staff_a, patient="alice")["report"]["id"])
    _observe(alice, own, "crp", 4.4, date(2025, 1, 1))
    _observe(alice, at_a, "crp", 9.0, date(2025, 2, 1))

    # Center B creates a report for Alice: it may see only what center B itself recorded.
    _create_report(staff_b, patient="alice")
    data = _as(staff_b).get("/api/trends/?marker=crp&patient=alice").data
    assert data["points"] == []
    assert [p["value"] for p in _as(staff_a).get("/api/trends/?marker=crp&patient=alice").data["points"]] == [9.0]
    assert len(_as(alice).get("/api/trends/?marker=crp").data["points"]) == 2


def test_unknown_and_unconsented_patients_get_the_same_error():
    staff = _staff("s", Center.objects.create(name="A"))
    _patient("no_consent", consent=False)
    body = {"original_filename": "a.pdf", "size_bytes": 10}
    unknown = _as(staff).post("/api/reports/", {**body, "patient": "nobody"})
    unconsented = _as(staff).post("/api/reports/", {**body, "patient": "no_consent"})
    assert unknown.status_code == unconsented.status_code == 400
    assert unknown.data == unconsented.data


@pytest.mark.django_db(transaction=True)
def test_concurrent_complete_queues_extraction_once(s3, monkeypatch):
    alice = _patient("alice")
    data = _create_report(alice)
    s3.put_object(Bucket=settings.REPORTS_BUCKET, Key=data["upload"]["fields"]["key"], Body=b"%PDF-1.7 body")
    queued: list[str] = []
    monkeypatch.setattr(views.extract_report, "delay", queued.append)
    real_verify = storage.verify_upload
    barrier = threading.Barrier(2)

    def slow_verify(key: str) -> int:
        time.sleep(RACE_WINDOW_S)  # Without the row lock, both requests pass the status check here.
        return real_verify(key)

    monkeypatch.setattr(storage, "verify_upload", slow_verify)
    results: list[int] = []

    def call() -> None:
        barrier.wait()
        try:
            results.append(_as(alice).post(f"/api/reports/{data['report']['id']}/complete/").status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    assert len(queued) == 1


def test_duplicate_task_delivery_skips_report_already_processing(s3, tmp_path, monkeypatch):
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))
    report.status = Report.Status.PROCESSING
    report.save()
    called = []
    monkeypatch.setattr(tasks, "analyse_report", lambda *a: called.append(a))
    assert tasks.extract_report(str(report.pk)) is None
    assert called == []


@pytest.mark.parametrize("day", [date.today() + timedelta(days=2), date(1800, 1, 1)])
def test_review_rejects_implausible_collection_dates(s3, tmp_path, day):
    alice = _patient("alice")
    report = _uploaded_report(s3, tmp_path, alice)
    report.status = Report.Status.NEEDS_REVIEW
    report.save()
    response = _as(alice).post(
        f"/api/reports/{report.pk}/review/",
        {"collected_on": day.isoformat(), "observations": [{"marker_code": "hb", "value": 13, "unit": "g/dL"}]},
        format="json",
    )
    assert response.status_code == 400 and "collected_on" in response.data


def test_observations_endpoint_scoped_and_logged(s3, tmp_path):
    alice, bob = _patient("alice"), _patient("bob")
    report = _uploaded_report(s3, tmp_path, alice)
    assert _as(bob).get(f"/api/reports/{report.pk}/observations/").status_code == 404
    response = _as(alice).get(f"/api/reports/{report.pk}/observations/")
    assert response.status_code == 200 and response.data["observations"] == []
    assert AccessLog.objects.filter(report=report, action="view", actor=alice).exists()


def test_download_unavailable_before_upload():
    alice = _patient("alice")
    report_id = _create_report(alice)["report"]["id"]
    assert _as(alice).get(f"/api/reports/{report_id}/download/").status_code == 409


def test_refresh_rotates_and_logout_revokes():
    _patient("alice")
    client = APIClient()
    tokens = client.post("/api/auth/token/", {"username": "alice", "password": PASSWORD}).data
    rotated = client.post("/api/auth/token/refresh/", {"refresh": tokens["refresh"]})
    assert rotated.status_code == 200 and rotated.data["refresh"] != tokens["refresh"]
    # The old refresh token is revoked by rotation; the new one by logout.
    assert client.post("/api/auth/token/refresh/", {"refresh": tokens["refresh"]}).status_code == 401
    assert client.post("/api/auth/logout/", {"refresh": rotated.data["refresh"]}).status_code == 200
    assert client.post("/api/auth/token/refresh/", {"refresh": rotated.data["refresh"]}).status_code == 401


def test_extraction_errors_shown_to_users_are_generic(s3, tmp_path, monkeypatch):
    report = _uploaded_report(s3, tmp_path, _patient("alice", llm_consent=True))

    def boom(*args):
        raise RuntimeError("/srv/app/secret/path exploded")

    monkeypatch.setattr(tasks, "analyse_report", boom)
    tasks.extract_report(str(report.pk))
    report.refresh_from_db()
    assert "/srv" not in report.error and report.error == tasks.EXTRACTION_FAILED


def test_patient_and_observation_still_linked_after_review(s3, tmp_path):
    # Guard for the staff scoping filter: observations keep pointing at their report's center.
    alice = _patient("alice")
    center = Center.objects.create(name="A")
    staff = _staff("sa", center)
    report = Report.objects.get(pk=_create_report(staff, patient="alice")["report"]["id"])
    _observe(alice, report, "hb", 13.0, date(2025, 1, 1))
    assert Observation.objects.filter(report__center=center).count() == 1
