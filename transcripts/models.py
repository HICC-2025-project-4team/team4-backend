from django.db import models

# Create your models here.
# transcripts/models.py
from django.db import models
from django.conf import settings

class Transcript(models.Model):
    STATUS_CHOICES = [
        ('pending',    '대기'),
        ('processing','처리 중'),
        ('done',       '완료'),
        ('error',      '오류'),
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
        default='pending'
    )
    parsed_data = models.JSONField(null=True, blank=True)  # 파싱 결과 저장
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transcript(user={self.user}, status={self.status})"


class TranscriptPage(models.Model):
    transcript   = models.ForeignKey(
        Transcript,
        on_delete=models.CASCADE,
        related_name='pages'
    )
    file         = models.FileField(upload_to='transcripts/pages/')
    page_number  = models.PositiveIntegerField()

    def __str__(self):
        return f"Page {self.page_number} of Transcript({self.transcript_id})"
    