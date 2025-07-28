from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    SignupView, LoginView,
    LogoutView, MeView, UpdateProfileView
)

urlpatterns = [
    # 회원가입
    path('signup/', SignupView.as_view(), name='signup'),
    # 로그인 → { access, refresh }
    path('login/',  LoginView.as_view(), name='token_obtain_pair'),
    # refresh 토큰으로 access 토큰 재발급
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # 로그아웃(블랙리스트)
    path('logout/', LogoutView.as_view(), name='logout'),
    # 내 정보 조회/수정
    path('me/', MeView.as_view(), name='me'),
    path('update-profile/', UpdateProfileView.as_view(), name='update-profile'),
]
