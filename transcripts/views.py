from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.shortcuts import get_object_or_404

from .models import Transcript
from .serializers import (
    TranscriptUploadSerializer,
    TranscriptStatusSerializer,
    TranscriptParsedSerializer
)
from .tasks import process_transcript

class TranscriptUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        # 본인 계정만 접근 허용
        if request.user.id != user_id:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        serializer = TranscriptUploadSerializer(data=request.data)
        if serializer.is_valid():
            transcript = serializer.save(user=request.user)
            process_transcript.delay(transcript.id)
            return Response(
                {"message": "업로드 완료", "status": "processing"},
                status=status.HTTP_201_CREATED
            )
        return Response(
            {"error": "지원하지 않는 파일 형식입니다."},
            status=status.HTTP_400_BAD_REQUEST
        )

class TranscriptStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        if request.user.id != user_id:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        transcript = get_object_or_404(Transcript, user_id=user_id)
        return Response(
            {"status": transcript.status},
            status=status.HTTP_200_OK
        )

class TranscriptParsedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        if request.user.id != user_id:
            return Response(
                {"error": "인증이 필요합니다."},
                status=status.HTTP_401_UNAUTHORIZED
                )
        
        try:
            transcript = Transcript.objects.get(user_id=user_id)
        except Transcript.DoesNotExist:
            return Response(
                {"error": "해당 성적표가 존재하지 않습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        if transcript.status != 'done':
            return Response(
                {"error": "아직 파싱이 완료되지 않았습니다."},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            transcript.parsed_data,
            status=status.HTTP_200_OK
        )
