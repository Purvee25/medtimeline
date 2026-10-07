import boto3
import pytest
from django.conf import settings
from moto import mock_aws

from reports import storage


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        storage._client.cache_clear()
        storage._presign_client.cache_clear()
        client = boto3.client("s3", region_name=settings.AWS_REGION)
        client.create_bucket(
            Bucket=settings.REPORTS_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION},
        )
        yield client
    storage._client.cache_clear()
    storage._presign_client.cache_clear()
