"""Create demo accounts and a year of synthetic results for local development and demos.

    python manage.py seed_demo

Refuses to run unless DEBUG is on. Idempotent: re-running resets the demo users' data.
All values are synthetic.
"""

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Center, Consent, User
from medtimeline_eval.markers import MARKERS
from reports.models import Observation, Report

DEMO_PASSWORD = "demo-password-123"  # noqa: S105 - local demo only; command refuses to run without DEBUG
PATIENT = "demo_patient"
STAFF = "demo_staff"

# (collection date, center or None for self-upload, {marker: value in canonical units}, verified)
HISTORY = [
    (date(2025, 11, 4), "Sunrise Diagnostics", {"crp": 18.2, "hb": 11.4, "wbc": 12.6, "plt": 410}, True),
    (date(2025, 12, 9), "Sunrise Diagnostics", {"crp": 11.5, "hb": 11.9, "wbc": 10.8, "plt": 372}, True),
    (date(2026, 1, 20), "Apex Pathlabs", {"crp": 6.1, "hb": 12.3, "chol": 214, "hdl": 41, "ldl": 138, "tg": 176}, True),
    (date(2026, 3, 3), "Apex Pathlabs", {"crp": 3.4, "hb": 12.8, "wbc": 8.1, "plt": 301}, True),
    (date(2026, 5, 12), None, {"crp": 7.9, "hb": 12.6}, True),
    (
        date(2026, 7, 28),
        "Sunrise Diagnostics",
        {"crp": 2.6, "hb": 13.2, "chol": 192, "hdl": 46, "ldl": 118, "tg": 141},
        False,
    ),
]


class Command(BaseCommand):
    help = __doc__

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG on; it creates accounts with a known password.")

        # Reports first: Report.uploaded_by is PROTECT.
        Report.objects.filter(patient__username=PATIENT).delete()
        User.objects.filter(username__in=[PATIENT, STAFF]).delete()

        centers = {name: Center.objects.get_or_create(name=name)[0] for name in {c for _, c, _, _ in HISTORY if c}}
        patient = User.objects.create_user(username=PATIENT, password=DEMO_PASSWORD)
        for purpose in Consent.Purpose:
            Consent.objects.create(user=patient, purpose=purpose, policy_version="demo")
        User.objects.create_user(
            username=STAFF, password=DEMO_PASSWORD, role=User.Role.CENTER_STAFF, center=centers["Sunrise Diagnostics"]
        )

        for i, (day, center_name, values, verified) in enumerate(HISTORY):
            report = Report.objects.create(
                patient=patient,
                center=centers.get(center_name) if center_name else None,
                uploaded_by=patient,
                s3_key=f"demo/{patient.pk}/{i}.pdf",
                original_filename=f"lab-report-{day.isoformat()}.pdf",
                size_bytes=48_000,
                status=Report.Status.EXTRACTED if verified else Report.Status.NEEDS_REVIEW,
                collected_on=day,
            )
            Observation.objects.bulk_create(
                Observation(
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
                for code, value in values.items()
            )

        self.stdout.write(f"Seeded {PATIENT} and {STAFF} with {len(HISTORY)} reports (see DEMO_PASSWORD in this file).")
