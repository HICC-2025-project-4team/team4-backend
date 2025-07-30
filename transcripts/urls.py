from django.urls import path
from .views import (
    TranscriptUploadView,
    TranscriptStatusView,
    TranscriptParsedView
)

urlpatterns = [
    # 1) POST   /api/transcripts/{user_id}/      -> 업로드
    path('<int:user_id>/', TranscriptUploadView.as_view(), name='transcript-upload'),
    # 2) GET    /api/transcripts/status/{user_id}/ -> OCR/파싱 상태 조회
    path('status/<int:user_id>/', TranscriptStatusView.as_view(), name='transcript-status'),
    # 3) GET    /api/transcripts/parsed/{user_id}/ -> 파싱 결과 조회
    path('parsed/<int:user_id>/', TranscriptParsedView.as_view(), name='transcript-parsed'),
]
