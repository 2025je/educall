from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView


class TokenThrottle(AnonRateThrottle):
    scope = "token"


class ActiveTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = RefreshToken(attrs["refresh"])
        user = get_user_model().objects.filter(pk=token["user_id"], is_active=True).first()
        if user is None or token.get("hash_password") != get_md5_hash_password(user.password):
            raise InvalidToken("La cuenta está inactiva o la contraseña cambió. Inicia sesión de nuevo.")
        return super().validate(attrs)


class ObtainTokenView(TokenObtainPairView):
    permission_classes = (AllowAny,)
    throttle_classes = (TokenThrottle,)


class RefreshTokenView(TokenRefreshView):
    serializer_class = ActiveTokenRefreshSerializer
    permission_classes = (AllowAny,)
    throttle_classes = (TokenThrottle,)


class RevokeTokenView(TokenBlacklistView):
    permission_classes = (IsAuthenticated,)
    authentication_classes = (JWTAuthentication, SessionAuthentication)

    def post(self, request, *args, **kwargs):
        raw = request.data.get("refresh") if isinstance(request.data, dict) else None
        if not raw:
            raise serializers.ValidationError("Indica el token de renovación.")
        token = RefreshToken(raw)
        if str(token["user_id"]) != str(request.user.pk):
            raise serializers.ValidationError("El token no pertenece a tu cuenta.")
        return super().post(request, *args, **kwargs)
