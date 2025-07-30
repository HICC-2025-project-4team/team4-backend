from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
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
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, user_id):
        # 본인 계정만 접근 허용
        if request.user.id != user_id:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        serializer = TranscriptUploadSerializer(
            data=request.data,
            context={'request':request}
        )
        if serializer.is_valid():
            transcript = serializer.save()
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
        # 1) 인증 체크
        if request.user.id != user_id:
            return Response(
                {"error": "인증이 필요합니다."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 2) 최신 업로드 한 건만 조회
        transcript = (
            Transcript.objects
                       .filter(user_id=user_id)
                       .order_by('-created_at')
                       .first()
        )
        if not transcript:
            return Response(
                {"error": "해당 성적표가 존재하지 않습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3) 상태 반환 (소문자)
        return Response(
            {"status": transcript.status.lower()},
            status=status.HTTP_200_OK
        )

class TranscriptParsedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        # 1) 인증 체크
        if request.user.id != user_id:
            return Response(
                {"error": "인증이 필요합니다."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 2) 최신 업로드 건 한 건만 조회
        transcript = (
            Transcript.objects
                      .filter(user_id=user_id)
                      .order_by('-created_at')
                      .first()
        )
        if not transcript:
            return Response(
                {"error": "해당 성적표가 존재하지 않습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3) 파싱 완료 여부 체크
        if transcript.status.lower() != 'done':
            return Response(
                {"error": "아직 파싱이 완료되지 않았습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 4) 파싱된 JSON 데이터 반환
        return Response(
            transcript.parsed_data,
            status=status.HTTP_200_OK
        )