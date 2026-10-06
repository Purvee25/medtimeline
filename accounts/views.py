from django.utils import timezone
from rest_framework import generics, permissions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from reports.services import erase_patient

from .models import Consent
from .serializers import CONSENT_POLICY_VERSION, MeSerializer, PatientRegistrationSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = PatientRegistrationSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_scope = "auth"


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_scope = "auth"


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
