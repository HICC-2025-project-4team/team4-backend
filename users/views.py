from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from .models import User
from .serializers import SignupSerializer, UserSerializer, CustomTokenObtainPairSerializer

# 회원가입(student_id, full_name)
class SignupView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = SignupSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            # 에러 dict 예시: {'current_year': ['현재 학년을 입력해주세요.'], 'major': …}
            errors = serializer.errors
            field, messages = next(iter(errors.items()))  # 첫 번째 필드와 메시지 리스트
            return Response(
                {'error_message': messages[0]},
                status=status.HTTP_400_BAD_REQUEST
            )
        user = serializer.save()
        return Response(
            {
                "message": "회원가입 성공",
                "user_id": user.id
            },
            status=status.HTTP_201_CREATED
        )

# JWT 로그인 (access/refresh 토큰 발급)
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        try:
            # 정상적인 경우 super() 안에서 serializer.validate() → 토큰 리턴
            return super().post(request, *args, **kwargs)
        except AuthenticationFailed as e:
            # 커스터마이징한 메시지를 key를 바꿔 반환하고 싶다면 여기서 처리
            return Response(
                {'error': str(e.detail)}, 
                status=status.HTTP_401_UNAUTHORIZED
            )

# 로그아웃: refresh token을 블랙리스트 처리
class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'detail': 'refresh 토큰을 함께 보내주세요.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            RefreshToken(refresh_token).blacklist()
        except Exception:
            return Response(
                {'detail': '유효하지 않은 토큰입니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {'message': '성공적으로 로그아웃 되었습니다.'},
            status=status.HTTP_200_OK
            )

# 내 정보 조회
class MeView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request, *args, **kwargs):
        user = request.user
        if not user or not user.is_authenticated:
            return Response(
                {"detail": "로그인이 필요합니다."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        sid = request.query_params.get('student_id')

        if sid.upper() != user.student_id:
            return Response(
                {"detail": "해당 학번의 사용자를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        data = self.get_serializer(user).data
        return Response(data, status=status.HTTP_200_OK)
    

# 내 정보 수정 (full_name, current_year 등)
class UpdateProfileView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
