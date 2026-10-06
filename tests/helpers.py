from rest_framework.test import APIClient

from accounts.models import Center, Consent, User

PASSWORD = "correct-horse-battery-9"


def _patient(username: str, consent: bool = True, llm_consent: bool = False) -> User:
    user = User.objects.create_user(username=username, password=PASSWORD)
    if consent:
        Consent.objects.create(user=user, purpose=Consent.Purpose.STORE_REPORTS, policy_version="test")
    if llm_consent:
        Consent.objects.create(user=user, purpose=Consent.Purpose.LLM_EXTRACTION, policy_version="test")
    return user


def _staff(username: str, center: Center) -> User:
    return User.objects.create_user(username=username, password=PASSWORD, role=User.Role.CENTER_STAFF, center=center)


def _as(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _create_report(user: User, **extra) -> dict:
    response = _as(user).post("/api/reports/", {"original_filename": "cbc.pdf", "size_bytes": 1000, **extra})
    assert response.status_code == 201, response.data
    return response.data
