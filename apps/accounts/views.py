from rest_framework import permissions, status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from .serializers import LoginSerializer, LogoutSerializer, RegistrationSerializer, UserSerializer

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegistrationSerializer

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({"user": UserSerializer(user).data, "access": str(refresh.access_token), "refresh": str(refresh)}, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError:
            from apps.customer_services.models import SecurityEvent
            email = str(request.data.get("email", ""))[:254]
            SecurityEvent.objects.create(
                event_type="failed_login",
                email=email,
                ip_address=self._client_ip(request),
            )
            raise
        payload = serializer.save()
        user = serializer.validated_data["user"]
        if user.role != "customer" and (not user.is_staff or not user.is_active):
            return Response({"detail": "Administrator access is not enabled."}, status=status.HTTP_403_FORBIDDEN)
        if user.role != "customer":
            from apps.customer_services.models import SecurityEvent
            SecurityEvent.objects.create(
                event_type="staff_login",
                email=user.email,
                ip_address=self._client_ip(request),
            )
        return Response(payload)

    @staticmethod
    def _client_ip(request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        return forwarded or request.META.get("REMOTE_ADDR") or None

class LogoutView(APIView):
    serializer_class = LogoutSerializer

    def post(self, request):
        try:
            RefreshToken(request.data["refresh"]).blacklist()
        except (KeyError, ValueError, TokenError):
            return Response({"detail": "A valid refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_205_RESET_CONTENT)

class MeView(APIView):
    serializer_class = UserSerializer

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
