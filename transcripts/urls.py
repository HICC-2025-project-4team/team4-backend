# transcripts/urls.py
from django.urls import path
from .views import (
    TranscriptUploadView,
    TranscriptStatusView,
    TranscriptParsedView
)

urlpatterns = [
    # POST /api/transcripts/
    path('', TranscriptUploadView.as_view(), name='transcript-upload'),

    # GET /api/transcripts/status/{transcript_id}/
    path('status/<int:transcript_id>/', TranscriptStatusView.as_view(), name='transcript-status'),

    # GET /api/transcripts/parsed/{transcript_id}/
    path('parsed/<int:transcript_id>/', TranscriptParsedView.as_view(), name='transcript-parsed'),
]
