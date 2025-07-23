from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User

class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    class Meta:
        model = User
        fields = ['student_id','password','full_name','entry_year','major']

    def create(self, validated_data):
        user = User(
            student_id=validated_data['student_id'],
            full_name=validated_data['full_name'],
            entry_year=validated_data['entry_year'],
            major=validated_data['major'],
            username=validated_data['student_id'],  # username 필드에도 student_id 넣기
        )
        user.set_password(validated_data['password'])
        user.save()
        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id','student_id','full_name','entry_year','major','email']
