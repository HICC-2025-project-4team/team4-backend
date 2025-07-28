from django.db import models

# Create your models here.
# transcripts/models.py
from django.db import models
from django.conf import settings

class Transcript(models.Model):
    STATUS_CHOICES = [
        ('PENDING',    '대기'),
        ('PROCESSING','처리 중'),
        ('DONE',       '완료'),
        ('ERROR',      '오류'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transcripts'
    )
    file = models.FileField(upload_to='transcripts/')
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    parsed = models.JSONField(null=True, blank=True)  # 파싱 결과 저장
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
