from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from .models import User

class SignupSerializer(serializers.ModelSerializer):
    student_id = serializers.RegexField(
        regex=r'^[A-Za-z]\d{6}$',
        max_length=7,
        error_messages={'invalid': '학번은 영문자 1자 + 숫자 6자리여야 합니다.'},
        validators=[
            UniqueValidator(
                queryset=User.objects.all(),
                message='이미 존재하는 학번입니다.'
            )
        ]
    )
    full_name = serializers.RegexField(
        regex=r'^[가-힣]{2,5}$',
        max_length=5,
        error_messages={
            'invalid': '이름은 한글 2~5자만 입력 가능합니다.',}
    )
    current_year = serializers.IntegerField(
        min_value=1, max_value=5,
        error_messages={
            'invalid': '유효한 학년을 입력하세요.',
            'required': '현재 학년을 입력해주세요.'
            }

    )
    major = serializers.CharField(
        max_length=100,
        error_messages={
            'required': '전공을 입력해주세요.'}
    )

    class Meta:
        model = User
        fields = ['student_id', 'full_name', 'current_year', 'major']

    def validate_student_id(self, value):
        # API 레벨에서 대문자로 정규화
        return value.upper()

    def create(self, validated_data):
        user = User(
            student_id=validated_data['student_id'],
            full_name=validated_data['full_name'],
            current_year=validated_data['current_year'],
            major=validated_data['major'],
            username=validated_data['student_id'],
        )
        user.set_unusable_password()
        user.save()
        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # 토큰 발급 시 payload 에 student_id, full_name 이 포함됩니다.
        fields = ['student_id', 'full_name', 'current_year', 'major']
        read_only_fields = ['student_id']  # student_id 는 수정 불가
