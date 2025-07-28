from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from .models import Transcript
from .serializers import (
    TranscriptUploadSerializer,
    TranscriptStatusSerializer,
    TranscriptParsedSerializer
)
from .tasks import process_transcript_ocr

class TranscriptUploadView(generics.CreateAPIView):
    queryset = Transcript.objects.all()
    serializer_class = TranscriptUploadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        inst = serializer.save(user=self.request.user)
        process_transcript_ocr.delay(inst.id)


class TranscriptStatusView(generics.RetrieveAPIView):
    queryset = Transcript.objects.all()
    serializer_class = TranscriptStatusSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = 'transcript_id'

    def get_object(self):
        obj = super().get_object()
        if obj.user != self.request.user:
            raise PermissionDenied()
        return obj


class TranscriptParsedView(generics.RetrieveAPIView):
    queryset = Transcript.objects.all()
    serializer_class = TranscriptParsedSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = 'transcript_id'

    def get_object(self):
        obj = super().get_object()
        if obj.user != self.request.user:
            raise PermissionDenied()
        if obj.status != 'DONE':
            raise PermissionDenied(detail='아직 처리 중입니다.')
        return obj
