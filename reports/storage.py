"""Thin S3 wrapper: pre-signed upload/download and post-upload verification."""

from functools import cache

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

PDF_MAGIC = b"%PDF-"
PDF_CONTENT_TYPE = "application/pdf"


class UploadVerificationError(Exception):
    """The uploaded object is missing, too large, or not a PDF."""


@cache
def _client():
    return boto3.client("s3", region_name=settings.AWS_REGION)


def presigned_upload(key: str) -> dict:
    """Pre-signed POST that only accepts a PDF up to MAX_REPORT_BYTES at exactly `key`."""
    return _client().generate_presigned_post(
        Bucket=settings.REPORTS_BUCKET,
        Key=key,
        Fields={"Content-Type": PDF_CONTENT_TYPE},
        Conditions=[
            {"Content-Type": PDF_CONTENT_TYPE},
            ["content-length-range", 1, settings.MAX_REPORT_BYTES],
        ],
        ExpiresIn=settings.PRESIGNED_URL_TTL_SECONDS,
    )


def presigned_download(key: str) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.REPORTS_BUCKET, "Key": key},
        ExpiresIn=settings.PRESIGNED_URL_TTL_SECONDS,
    )


def verify_upload(key: str) -> int:
    """Check the object exists, respects the size cap and starts with PDF magic bytes.

    Returns:
        Object size in bytes.

    Raises:
        UploadVerificationError: Any check fails. Rejected objects are deleted.
    """
    s3, bucket = _client(), settings.REPORTS_BUCKET
    try:
        size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    except ClientError as exc:
        raise UploadVerificationError("File not found in storage; upload it first.") from exc

    head = s3.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{len(PDF_MAGIC) - 1}")["Body"].read()
    if size > settings.MAX_REPORT_BYTES or head != PDF_MAGIC:
        s3.delete_object(Bucket=bucket, Key=key)
        raise UploadVerificationError("File is not a valid PDF within the size limit.")
    return size


def download_to(key: str, path) -> None:
    _client().download_file(settings.REPORTS_BUCKET, key, str(path))


def delete(key: str) -> None:
    _client().delete_object(Bucket=settings.REPORTS_BUCKET, Key=key)
