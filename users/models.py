# users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator

class User(AbstractUser):
    # 영문자 1자 + 숫자 6자리 (예: C135195)
    student_id = models.CharField(
        max_length=7,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Za-z]\d{6}$',
                message='학번은 영문자 1자와 숫자 6자리여야 합니다. (예: C135195)'
            )
        ]
    )
    # 한글만 2~5자
    full_name = models.CharField(
        max_length=5,
        validators=[
            RegexValidator(
                regex=r'^[가-힣]{2,5}$',
                message='이름은 한글 2~5자만 입력 가능합니다.'
            )
        ]
    )
    current_year  = models.PositiveSmallIntegerField(null=True, blank=True)
    major = models.CharField(max_length=100, blank=True)

    USERNAME_FIELD = 'student_id'
    REQUIRED_FIELDS = ['full_name']

    def save(self, *args, **kwargs):
        # student_id 를 항상 대문자로 변환
        if self.student_id:
            self.student_id = self.student_id.upper()
        super().save(*args, **kwargs)