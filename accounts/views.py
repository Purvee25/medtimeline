import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from reports.services import erase_patient

from .models import Consent, EmailVerificationToken
from .serializers import (
    CONSENT_POLICY_VERSION,
    EmailTokenObtainPairSerializer,
    MeSerializer,
    PatientRegistrationSerializer,
)

logger = logging.getLogger(__name__)


class RegisterView(generics.CreateAPIView):
    serializer_class = PatientRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def perform_create(self, serializer):
        user = serializer.save()
        # Send verification email (fire-and-forget; log failures rather than crashing).
        try:
            token_obj = EmailVerificationToken.objects.create(user=user)
            verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token_obj.token}"
            send_mail(
                subject="Verify your MedTimeline email",
                message=(
                    f"Hi {user.username},\n\n"
                    f"Click the link below to verify your email address (valid for 24 hours):\n\n"
                    f"{verify_url}\n\n"
                    "If you didn't sign up for MedTimeline, ignore this email.\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("Failed to send verification email", extra={"user_id": str(user.pk)})


class VerifyEmailView(APIView):
    """GET /api/auth/verify-email/?token=... marks the user's email as verified."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def get(self, request: Request) -> Response:
        token = request.query_params.get("token", "")
        try:
            token_obj = EmailVerificationToken.objects.select_related("user").get(token=token)
        except EmailVerificationToken.DoesNotExist:
            return Response({"detail": "Invalid or expired link."}, status=status.HTTP_400_BAD_REQUEST)
        if not token_obj.is_valid():
            token_obj.delete()
            return Response(
                {"detail": "This link has expired. Please register again."}, status=status.HTTP_400_BAD_REQUEST
            )
        token_obj.user.email_verified = True
        token_obj.user.save(update_fields=["email_verified"])
        token_obj.delete()
        return Response({"detail": "Email verified. You can now sign in."})

    def post(self, request: Request) -> Response:
        """POST {"token": "..."} — same as GET, for frontend fetch calls."""
        token = request.data.get("token", "")
        return self.get(
            Request(request._request.__class__(request._request.environ | {"QUERY_STRING": f"token={token}"}))
        )


class ResendVerificationView(APIView):
    """POST {"email": "..."} resends the verification email."""

    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"

    def post(self, request: Request) -> Response:
        email = request.data.get("email", "").lower()
        # Generic response regardless of whether the email exists (no enumeration).
        try:
            from .models import User

            user = User.objects.get(email__iexact=email, email_verified=False)
            EmailVerificationToken.objects.filter(user=user).delete()
            token_obj = EmailVerificationToken.objects.create(user=user)
            verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token_obj.token}"
            send_mail(
                subject="Verify your MedTimeline email",
                message=f"Your new verification link (valid 24 hours):\n\n{verify_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass
        return Response({"detail": "If that email is registered and unverified, we sent a new link."})


class EmailTokenObtainPairView(TokenObtainPairView):
    """Login with email + password."""

    serializer_class = EmailTokenObtainPairSerializer
    throttle_scope = "auth"


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_scope = "refresh"


class LogoutView(TokenBlacklistView):
    """POST {"refresh": ...} revokes that refresh token. Access tokens expire within 15 minutes."""

    throttle_scope = "refresh"


class MeView(generics.RetrieveDestroyAPIView):
    """GET the current user; DELETE erases a patient's account and all their reports."""

    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        if not request.user.is_patient:
            return Response(
                {"detail": "Staff accounts are removed by an administrator."}, status=status.HTTP_403_FORBIDDEN
            )
        erase_patient(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConsentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Consent
        fields = ["purpose", "policy_version", "granted_at", "withdrawn_at"]
        read_only_fields = fields


class ConsentView(APIView):
    """GET lists consents; POST {"purpose": ..., "granted": bool} grants or withdraws one."""

    def get(self, request: Request) -> Response:
        return Response(ConsentSerializer(request.user.consents.order_by("granted_at"), many=True).data)

    def post(self, request: Request) -> Response:
        purpose = request.data.get("purpose")
        if purpose not in Consent.Purpose.values or not isinstance(request.data.get("granted"), bool):
            return Response({"detail": "Expected purpose and boolean granted."}, status=status.HTTP_400_BAD_REQUEST)
        active = request.user.consents.filter(purpose=purpose, withdrawn_at__isnull=True)
        if request.data["granted"]:
            if not active.exists():
                Consent.objects.create(user=request.user, purpose=purpose, policy_version=CONSENT_POLICY_VERSION)
        else:
            active.update(withdrawn_at=timezone.now())
        return self.get(request)
