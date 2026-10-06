import pytest
from django.conf import settings
from rest_framework.test import APIClient

from accounts.models import Center, Consent, User
from reports.models import AccessLog, Report
from tests.helpers import PASSWORD, _as, _create_report, _patient, _staff

pytestmark = pytest.mark.django_db


# --- auth -----------------------------------------------------------------


def test_register_records_consent_and_jwt_login_works():
    response = APIClient().post(
        "/api/auth/register/",
        {"username": "asha", "password": PASSWORD, "consent_store_reports": True, "consent_llm_extraction": False},
    )
    assert response.status_code == 201
    user = User.objects.get(username="asha")
    assert user.role == User.Role.PATIENT
    assert list(user.consents.values_list("purpose", flat=True)) == [Consent.Purpose.STORE_REPORTS]

    token = APIClient().post("/api/auth/token/", {"username": "asha", "password": PASSWORD}).data["access"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get("/api/auth/me/").data["role"] == "patient"


def test_register_requires_storage_consent_and_strong_password():
    response = APIClient().post(
        "/api/auth/register/",
        {"username": "x", "password": "123", "consent_store_reports": False, "consent_llm_extraction": False},
    )
    assert response.status_code == 400
    assert {"password", "consent_store_reports"} <= response.data.keys()


def test_unauthenticated_requests_are_rejected():
    assert APIClient().get("/api/reports/").status_code == 401


# --- object-level access --------------------------------------------------


def test_patient_cannot_see_or_download_another_patients_report():
    alice, bob = _patient("alice"), _patient("bob")
    report_id = _create_report(alice)["report"]["id"]

    bob_client = _as(bob)
    assert bob_client.get(f"/api/reports/{report_id}/").status_code == 404
    assert bob_client.get(f"/api/reports/{report_id}/download/").status_code == 404
    assert bob_client.post(f"/api/reports/{report_id}/complete/").status_code == 404
    assert bob_client.get("/api/reports/").data["count"] == 0


def test_staff_see_only_their_centers_reports():
    alice = _patient("alice")
    center_a, center_b = Center.objects.create(name="A"), Center.objects.create(name="B")
    staff_a, staff_b = _staff("staff_a", center_a), _staff("staff_b", center_b)
    report_id = _create_report(staff_a, patient="alice")["report"]["id"]

    assert _as(staff_a).get(f"/api/reports/{report_id}/").status_code == 200
    assert _as(staff_b).get(f"/api/reports/{report_id}/").status_code == 404
    assert _as(alice).get(f"/api/reports/{report_id}/").status_code == 200


def test_staff_must_name_patient_and_patient_cannot_upload_for_others():
    center = Center.objects.create(name="A")
    assert (
        _as(_staff("s", center)).post("/api/reports/", {"original_filename": "a.pdf", "size_bytes": 10}).status_code
        == 400
    )

    alice, _ = _patient("alice"), _patient("bob")
    data = _create_report(alice, patient="bob")
    assert data["report"]["patient"] == "alice"


def test_upload_blocked_without_consent():
    response = _as(_patient("noconsent", consent=False)).post(
        "/api/reports/", {"original_filename": "a.pdf", "size_bytes": 10}
    )
    assert response.status_code == 403


# --- upload flow ----------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"original_filename": "a.exe", "size_bytes": 10},
        {"original_filename": "a.pdf", "size_bytes": 10**9},
        {"original_filename": "a.pdf", "size_bytes": 0},
    ],
)
def test_create_rejects_bad_metadata(payload):
    assert _as(_patient("alice")).post("/api/reports/", payload).status_code == 400


def test_presigned_upload_is_scoped_to_pdf_and_size():
    upload = _create_report(_patient("alice"))["upload"]
    assert upload["fields"]["Content-Type"] == "application/pdf"
    assert upload["fields"]["key"].startswith("reports/")


def test_complete_accepts_real_pdf_and_logs_access(s3):
    alice = _patient("alice")
    data = _create_report(alice)
    s3.put_object(Bucket=settings.REPORTS_BUCKET, Key=data["upload"]["fields"]["key"], Body=b"%PDF-1.7 fake body")

    client = _as(alice)
    response = client.post(f"/api/reports/{data['report']['id']}/complete/")
    assert response.status_code == 200 and response.data["status"] == "uploaded"
    assert client.post(f"/api/reports/{data['report']['id']}/complete/").status_code == 409
    assert "X-Amz-Signature" in client.get(f"/api/reports/{data['report']['id']}/download/").data["url"]
    assert set(AccessLog.objects.values_list("action", flat=True)) == {"create", "download"}


def test_complete_rejects_and_deletes_non_pdf(s3):
    alice = _patient("alice")
    data = _create_report(alice)
    key = data["upload"]["fields"]["key"]
    s3.put_object(Bucket=settings.REPORTS_BUCKET, Key=key, Body=b"MZ\x90\x00 malware")

    response = _as(alice).post(f"/api/reports/{data['report']['id']}/complete/")
    assert response.status_code == 400
    assert Report.objects.get(pk=data["report"]["id"]).status == Report.Status.REJECTED
    assert s3.list_objects_v2(Bucket=settings.REPORTS_BUCKET).get("KeyCount", 0) == 0


def test_complete_before_upload_fails():
    alice = _patient("alice")
    report_id = _create_report(alice)["report"]["id"]
    assert _as(alice).post(f"/api/reports/{report_id}/complete/").status_code == 400


def test_staff_cannot_complete_upload_started_by_patient():
    center = Center.objects.create(name="A")
    alice = _patient("alice")
    report = Report.objects.get(pk=_create_report(alice)["report"]["id"])
    report.center = center
    report.save()
    assert _as(_staff("s", center)).post(f"/api/reports/{report.pk}/complete/").status_code == 403
