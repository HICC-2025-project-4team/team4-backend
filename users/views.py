from django.shortcuts import render

from rest_framework import generics, permissions
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView
)
from .models import User
from .serializers import SignupSerializer, UserSerializer

# 회원가입
class SignupView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = SignupSerializer

# JWT 로그인 (토큰 발급)
class LoginView(TokenObtainPairView):
    # default serializer: TokenObtainPairSerializer
    pass

# 내 정보 조회
class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
