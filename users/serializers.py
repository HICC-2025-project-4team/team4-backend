from rest_framework import serializers
from .models import User

class SignupSerializer(serializers.ModelSerializer):
    student_id = serializers.RegexField(
        regex=r'^[A-Za-z]\d{6}$',
        max_length=7,
        error_messages={'invalid': '학번은 영문자 1자 + 숫자 6자리여야 합니다.'}
    )
    full_name = serializers.RegexField(
        regex=r'^[가-힣]{2,5}$',
        max_length=5,
        error_messages={'invalid': '이름은 한글 2~5자만 입력 가능합니다.'}
    )

    class Meta:
        model = User
        fields = ['student_id', 'full_name']

    def validate_student_id(self, value):
        # API 레벨에서 대문자로 정규화
        return value.upper()

    def create(self, validated_data):
        user = User(
            student_id=validated_data['student_id'],
            full_name=validated_data['full_name'],
            username=validated_data['student_id'],
        )
        user.set_unusable_password()
        user.save()
        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # 토큰 발급 시 payload 에 student_id, full_name 이 포함됩니다.
        fields = ['student_id', 'full_name', 'current_year']
        read_only_fields = ['student_id']  # student_id 는 수정 불가
