from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.management import call_command


def test_existing_bucket_is_not_recreated():
    # Bucket-scoped credentials (e.g. Cloudflare R2 tokens) are denied CreateBucket.
    client = MagicMock()
    with patch("reports.management.commands.ensure_bucket._client", return_value=client):
        call_command("ensure_bucket", retries=1, delay=0)
    client.head_bucket.assert_called_once_with(Bucket=settings.REPORTS_BUCKET)
    client.create_bucket.assert_not_called()


def test_missing_bucket_is_created(s3):
    s3.delete_bucket(Bucket=settings.REPORTS_BUCKET)
    call_command("ensure_bucket", retries=1, delay=0)
    s3.head_bucket(Bucket=settings.REPORTS_BUCKET)
