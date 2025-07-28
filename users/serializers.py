from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from .models import User
from rest_framework.exceptions import AuthenticationFailed

class SignupSerializer(serializers.ModelSerializer):
    student_id = serializers.RegexField(
        regex=r'^[A-Za-z]\d{6}$',
        max_length=7,
        error_messages={'invalid': '학번은 영문자 1자 + 숫자 6자리여야 합니다.'},
        validators=[
            UniqueValidator(
                queryset=User.objects.all(),
                lookup='iexact',
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
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        error_messages={
            'min_length': '비밀번호는 최소 8자 이상이어야 합니다.',
            'blank': '비밀번호를 입력해주세요.'
        }
    )

    class Meta:
        model = User
        fields = ['student_id', 'full_name', 'current_year', 'major', 'password']

    def validate_student_id(self, value):
        # API 레벨에서 대문자로 정규화
        return value.upper()

    def create(self, validated_data):
        pwd = validated_data.pop('password')
        user = User(
            student_id=validated_data['student_id'],
            full_name=validated_data['full_name'],
            current_year=validated_data['current_year'],
            major=validated_data['major'],
            username=validated_data['student_id'],
        )
        user.set_password(pwd)
        user.save()
        return user

class UserSerializer(serializers.ModelSerializer):
    # write_only으로만 받고, 응답엔 포함되지 않습니다
    password = serializers.CharField(
        write_only=True,
        required=False,
        min_length=8,
        error_messages={'min_length': '비밀번호는 최소 8자 이상이어야 합니다.'}
    )

    class Meta:
        model = User
        fields = ['student_id', 'full_name', 'current_year', 'major', 'password']
        read_only_fields = ['student_id']

    def update(self, instance, validated_data):
        # 1) password 처리
        pwd = validated_data.pop('password', None)
        # 2) 나머지 필드 업데이트
        instance = super().update(instance, validated_data)
        # 3) 비밀번호가 들어왔으면 set_password
        if pwd:
            instance.set_password(pwd)
            instance.save()
        return instance


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        student_id = attrs.get('student_id').upper()
        password   = attrs.get('password')

        # 1) 실제 인증 시도
        user = authenticate(username=student_id, password=password)
        if user is None:
            # 2) 학번만 있는지 확인
            if User.objects.filter(student_id__iexact=student_id).exists():
                raise AuthenticationFailed('비밀번호를 잘못 입력하셨습니다.')
            else:
                raise AuthenticationFailed('존재하지 않는 회원입니다.')

        attrs['student_id'] = student_id

        # 3) 기본 토큰 발급 로직
        return super().validate(attrs)