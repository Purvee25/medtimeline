"""Background extraction of uploaded reports."""

import logging
import tempfile
from pathlib import Path

import anthropic
from botocore.exceptions import BotoCoreError
from celery import shared_task
from django.db import transaction

from accounts.models import Consent
from medtimeline_extract.pipeline import analyse_report

from . import storage
from .models import Report
from .services import save_extraction

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_SECONDS = 30
RETRYABLE = (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError, BotoCoreError)


def _claim(report_id: str) -> Report | None:
    """Move UPLOADED → PROCESSING under a row lock so duplicate deliveries are no-ops."""
    with transaction.atomic():
        report = Report.objects.select_for_update().filter(pk=report_id).first()
        if report is None or report.status not in {Report.Status.UPLOADED, Report.Status.PROCESSING}:
            return None
        report.status = Report.Status.PROCESSING
        report.save(update_fields=["status", "updated_at"])
        return report


def _fail(report: Report, reason: str) -> None:
    report.status = Report.Status.FAILED
    report.error = reason
    report.save(update_fields=["status", "error", "updated_at"])


@shared_task(bind=True, max_retries=MAX_RETRIES)
def extract_report(self, report_id: str) -> str | None:
    """Download, extract and store results for one report. Returns the final status."""
    report = _claim(report_id)
    if report is None:
        logger.info("Skipping report not awaiting extraction", extra={"report_id": report_id})
        return None

    llm_allowed = report.patient.consents.filter(
        purpose=Consent.Purpose.LLM_EXTRACTION, withdrawn_at__isnull=True
    ).exists()
    if not llm_allowed:
        save_extraction(report, {"status": Report.Status.NEEDS_REVIEW, "skipped": "no_llm_consent", "results": []})
        return report.status

    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "report.pdf"
            storage.download_to(report.s3_key, pdf)
            result = analyse_report(pdf, anthropic.Anthropic())
    except RETRYABLE as exc:
        if self.request.retries < MAX_RETRIES:
            logger.warning("Transient extraction error, retrying", extra={"report_id": report_id})
            raise self.retry(exc=exc, countdown=RETRY_BASE_SECONDS * 2**self.request.retries) from exc
        logger.exception("Extraction failed after retries", extra={"report_id": report_id})
        _fail(report, f"{type(exc).__name__} after {MAX_RETRIES} retries")
        return report.status
    except Exception as exc:
        logger.exception("Extraction failed", extra={"report_id": report_id})
        _fail(report, f"{type(exc).__name__}: {exc}")
        return report.status

    save_extraction(report, result)
    return report.status
