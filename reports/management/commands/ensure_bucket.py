"""Create the reports S3 bucket if it does not already exist.

Run this as part of the pre-deploy command so the bucket is ready before
the first upload request arrives:

    python manage.py migrate --noinput && python manage.py ensure_bucket
"""

import time

from botocore.exceptions import ClientError, EndpointResolutionError
from django.conf import settings
from django.core.management.base import BaseCommand

from reports.storage import _client


def _bucket_exists(client, bucket: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            return False
        raise
    return True


class Command(BaseCommand):
    help = "Create the reports S3 bucket if it does not already exist."

    def add_arguments(self, parser):
        parser.add_argument("--retries", type=int, default=10)
        parser.add_argument("--delay", type=float, default=3.0)

    def handle(self, *args, **options):
        bucket = settings.REPORTS_BUCKET
        region = settings.AWS_REGION

        for attempt in range(1, options["retries"] + 1):
            try:
                client = _client()
                # Bucket-scoped credentials (e.g. an R2 token) can't create buckets, so check first.
                if _bucket_exists(client, bucket):
                    self.stdout.write(f"Bucket '{bucket}' already exists — OK.")
                    return
                if region == "us-east-1":
                    client.create_bucket(Bucket=bucket)
                else:
                    client.create_bucket(
                        Bucket=bucket,
                        CreateBucketConfiguration={"LocationConstraint": region},
                    )
                self.stdout.write(self.style.SUCCESS(f"Bucket '{bucket}' created."))
                return
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    self.stdout.write(f"Bucket '{bucket}' already exists — OK.")
                    return
                self.stderr.write(f"Attempt {attempt}: {exc}")
            except (EndpointResolutionError, OSError) as exc:
                self.stderr.write(f"Attempt {attempt}: S3 not reachable yet — {exc}")

            if attempt < options["retries"]:
                time.sleep(options["delay"])

        raise SystemExit(f"Could not reach S3 after {options['retries']} attempts.")
