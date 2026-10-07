import logging
import uuid

from django.db import transaction
from django.db.models import QuerySet
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Consent, User

from . import storage
from .models import AccessLog, Report
from .serializers import ObservationSerializer, ReportCreateSerializer, ReportSerializer, ReviewSerializer
from .services import ReviewedValue, ReviewError, apply_review
from .tasks import extract_report

logger = logging.getLogger(__name__)


def reports_visible_to(user: User) -> QuerySet[Report]:
    """Object-level access rule: patients see their own reports, staff see their center's."""
    if user.is_patient:
        return Report.objects.filter(patient=user)
    if user.is_center_staff:
        return Report.objects.filter(center_id=user.center_id)
    return Report.objects.none()


def _log(request: Request, action: str, report: Report | None = None, patient: User | None = None) -> None:
    AccessLog.objects.create(
        actor=request.user, action=action, report=report, patient=patient or (report.patient if report else None)
    )


class ReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Reports outside the caller's scope return 404, not 403, so IDs can't be probed."""

    serializer_class = ReportSerializer

    def get_queryset(self) -> QuerySet[Report]:
        return reports_visible_to(self.request.user).select_related("patient", "center")

    def list(self, request: Request, *args, **kwargs) -> Response:
        _log(request, AccessLog.Action.LIST, patient=request.user if request.user.is_patient else None)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        report = self.get_object()
        _log(request, AccessLog.Action.VIEW, report)
        return Response(ReportSerializer(report).data)

    @transaction.atomic
    def create(self, request: Request) -> Response:
        """Register a report and return a pre-signed POST for the client to upload the PDF to S3."""
        serializer = ReportCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        patient: User = serializer.validated_data["patient"]
        has_consent = patient.consents.filter(purpose=Consent.Purpose.STORE_REPORTS, withdrawn_at__isnull=True).exists()
        if not has_consent:
            raise PermissionDenied("You have not consented to report storage.")

        report = Report.objects.create(
            patient=patient,
            center=request.user.center,
            uploaded_by=request.user,
            s3_key=f"reports/{patient.pk}/{uuid.uuid4()}.pdf",
            original_filename=serializer.validated_data["original_filename"],
            size_bytes=serializer.validated_data["size_bytes"],
        )
        _log(request, AccessLog.Action.CREATE, report)
        return Response(
            {"report": ReportSerializer(report).data, "upload": storage.presigned_upload(report.s3_key)},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def observations(self, request: Request, pk: str | None = None) -> Response:
        """Stored values plus the raw extraction (with validation issues) for the reviewer."""
        report = self.get_object()
        _log(request, AccessLog.Action.VIEW, report)
        return Response(
            {
                "report": ReportSerializer(report).data,
                "extraction": report.extraction,
                "observations": ObservationSerializer(report.observations.order_by("marker_code"), many=True).data,
            }
        )

    @action(detail=True, methods=["post"])
    def review(self, request: Request, pk: str | None = None) -> Response:
        """Replace the report's values with human-verified ones and mark it extracted."""
        report = self.get_object()
        reviewable = {Report.Status.NEEDS_REVIEW, Report.Status.EXTRACTED, Report.Status.FAILED}
        if report.status not in reviewable:
            return Response(
                {"detail": f"Report is {report.status}; cannot review yet."}, status=status.HTTP_409_CONFLICT
            )
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = [ReviewedValue(**o) for o in serializer.validated_data["observations"]]
        try:
            apply_review(report, serializer.validated_data["collected_on"], rows)
        except ReviewError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _log(request, AccessLog.Action.REVIEW, report)
        return Response(ObservationSerializer(report.observations.order_by("marker_code"), many=True).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def complete(self, request: Request, pk: str | None = None) -> Response:
        """Called after the S3 upload: verifies the object and marks the report uploaded.

        The row lock makes concurrent calls serialise: the second sees UPLOADED and gets 409,
        so extraction is queued exactly once.
        """
        report = self.get_queryset().select_for_update(of=("self",)).get(pk=self.get_object().pk)
        if report.uploaded_by_id != request.user.pk:
            raise PermissionDenied("Only the uploader can complete this upload.")
        if report.status != Report.Status.AWAITING_UPLOAD:
            return Response({"detail": f"Report is already {report.status}."}, status=status.HTTP_409_CONFLICT)
        try:
            report.size_bytes = storage.verify_upload(report.s3_key)
        except storage.UploadVerificationError as exc:
            report.status = Report.Status.REJECTED
            report.save(update_fields=["status", "updated_at"])
            logger.warning("Upload rejected", extra={"report_id": str(report.pk), "reason": str(exc)})
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        report.status = Report.Status.UPLOADED
        report.save(update_fields=["size_bytes", "status", "updated_at"])
        transaction.on_commit(lambda: extract_report.delay(str(report.pk)))
        return Response(ReportSerializer(report).data)

    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> Response:
        report = self.get_object()
        if report.status in {Report.Status.AWAITING_UPLOAD, Report.Status.REJECTED}:
            return Response({"detail": "No file available."}, status=status.HTTP_409_CONFLICT)
        _log(request, AccessLog.Action.DOWNLOAD, report)
        return Response({"url": storage.presigned_download(report.s3_key)})

    @action(detail=True, methods=["post"])
    def share(self, request: Request, pk: str | None = None) -> Response:
        """Create a 72-hour read-only share token for this report (patient only)."""
        report = self.get_object()
        if not request.user.is_patient or report.patient_id != request.user.pk:
            raise PermissionDenied("Only the patient who owns this report can share it.")
        token = ReportShareToken.objects.create(report=report)
        from django.conf import settings

        share_url = f"{settings.FRONTEND_URL}/shared/{token.token}"
        _log(request, AccessLog.Action.DOWNLOAD, report)  # reuse DOWNLOAD action for audit
        return Response({"url": share_url, "expires_at": token.expires_at})


class SharedReportView(APIView):
    """Public read-only view of a report via share token (no auth required)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request, token: str) -> Response:
        try:
            token_obj = ReportShareToken.objects.select_related("report", "report__patient", "report__center").get(
                token=token
            )
        except ReportShareToken.DoesNotExist:
            return Response({"detail": "Invalid or expired share link."}, status=status.HTTP_404_NOT_FOUND)
        if not token_obj.is_valid():
            token_obj.delete()
            return Response({"detail": "This share link has expired."}, status=status.HTTP_410_GONE)
        report = token_obj.report
        return Response(
            {
                "report": ReportSerializer(report).data,
                "observations": ObservationSerializer(
                    report.observations.filter(verified=True).order_by("marker_code"), many=True
                ).data,
                "expires_at": token_obj.expires_at,
            }
        )
