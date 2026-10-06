"""Measure the trend query with and without the (patient, loinc, effective_date) index.

Seeds synthetic observations inside a transaction that is always rolled back, so it is
safe to run against a dev database. Prints both query plans and timings.

    python manage.py explain_trends --patients 2000 --per-patient 50
"""

import random
from datetime import date, timedelta

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from accounts.models import User
from medtimeline_eval.markers import MARKERS
from reports.models import Observation, Report

SEED = 42
BATCH = 5000


class _Rollback(Exception):
    pass


def _explain(sql: str, params: list) -> tuple[str, float]:
    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", params)
        plan = cursor.fetchone()[0][0]
    node = plan["Plan"]
    while node.get("Plans") and node["Node Type"] in {"Sort", "Limit", "Gather"}:
        node = node["Plans"][0]
    return node["Node Type"], plan["Execution Time"]


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--patients", type=int, default=2000)
        parser.add_argument("--per-patient", type=int, default=50)

    def handle(self, *args, patients: int, per_patient: int, **options):
        try:
            with transaction.atomic():
                self._run(patients, per_patient)
                raise _Rollback
        except _Rollback:
            self.stdout.write("Seed data rolled back.")

    def _run(self, patients: int, per_patient: int) -> None:
        rng = random.Random(SEED)
        codes = list(MARKERS)
        unusable = make_password(None)
        users = User.objects.bulk_create(User(username=f"bench_{i}", password=unusable) for i in range(patients))
        reports = Report.objects.bulk_create(
            Report(patient=u, uploaded_by=u, s3_key=f"bench/{u.pk}", original_filename="b.pdf", size_bytes=1)
            for u in users
        )
        rows = []
        for user, report in zip(users, reports, strict=True):
            for i in range(per_patient):
                code = codes[i % len(codes)]
                value = round(rng.uniform(*MARKERS[code].normal_range), 2)
                rows.append(
                    Observation(
                        patient=user,
                        report=report,
                        marker_code=f"{code}_{i}",
                        loinc=MARKERS[code].loinc,
                        value=value,
                        unit="u",
                        canonical_value=value,
                        canonical_unit="u",
                        effective_date=date(2024, 1, 1) + timedelta(days=i * 7),
                    )
                )
        Observation.objects.bulk_create(rows, batch_size=BATCH)
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE reports_observation")

        target = users[len(users) // 2]
        qs = Observation.objects.filter(patient=target, loinc=MARKERS["crp"].loinc).order_by("effective_date")
        sql, params = qs.values("effective_date", "canonical_value").query.sql_with_params()

        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_indexscan = off; SET LOCAL enable_bitmapscan = off")
        before = _explain(sql, list(params))
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_indexscan = on; SET LOCAL enable_bitmapscan = on")
        after = _explain(sql, list(params))

        self.stdout.write(f"Observations: {len(rows):,} across {patients:,} patients")
        self.stdout.write(f"Without index: {before[0]:<20} {before[1]:8.2f} ms")
        self.stdout.write(f"With index:    {after[0]:<20} {after[1]:8.2f} ms")
