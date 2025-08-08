from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status, permissions
from django.shortcuts import get_object_or_404
from .custom_paddle_ocr_script import rows_to_text, parse_transcript_tokens
from django.http import HttpResponse

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
        if request.user.id != user_id:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        
        # 'files' 키가 request.data에 있는지 확인
        if 'files' not in request.data:
            return Response(
                {"error": "파일이 전송되지 않았습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = TranscriptUploadSerializer(
            data={"files": request.data.getlist('files')}, # files를 리스트로 감싸서 전달
            context={'request': request}
        )
        if serializer.is_valid():
            transcript = serializer.save()
            process_transcript.delay(transcript.id)
            # Serializer의 응답을 그대로 사용하거나, 기존처럼 직접 구성할 수 있습니다.
            # 여기서는 API 명세에 맞게 직접 구성합니다.
            return Response(
                {"message": "업로드 완료", "status": "processing"},
                status=status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors, # 에러가 발생하면 serializer의 에러 메시지를 전달
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
        if request.user.id != user_id:
            return Response(
                {"error": "인증이 필요합니다."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        transcript = Transcript.objects.filter(user_id=user_id).order_by('-created_at').first()
        
        if not transcript:
            return Response(
                {"error": "해당 성적표가 존재하지 않습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 상태가 'done'이 아니거나, 'done'인데 데이터가 없는 경우
        if transcript.status.lower() != 'done' or not transcript.parsed_data:
            return Response(
                {"error": "아직 파싱이 완료되지 않았거나 결과가 없습니다."},
                status=status.HTTP_404_NOT_FOUND # 명세에 따라 404 유지
            )

        # 파싱된 JSON 데이터를 그대로 반환
                # 파싱된 JSON 데이터를 그대로 반환  ← 이 부분을 전부 교체
        data = transcript.parsed_data

        # 권장 케이스: 2차원 rows로 저장된 경우
        if isinstance(data, list) and data and isinstance(data[0], list):
            tsv = rows_to_text(data)
            return HttpResponse(tsv, content_type="text/plain; charset=utf-8")

        # 예전 flat 토큰 리스트가 남아있는 경우 폴백
        if isinstance(data, list) and (not data or isinstance(data[0], str)):
            rows = parse_transcript_tokens(data)   # 토큰 → rows 복원
            tsv = rows_to_text(rows)
            return HttpResponse(tsv, content_type="text/plain; charset=utf-8")

        # 이미 문자열로 저장돼 있다면 그대로
        if isinstance(data, str):
            return HttpResponse(data, content_type="text/plain; charset=utf-8")

        # 그 외 형식 오류
        return Response(
            {"error": "파싱 결과 형식이 올바르지 않습니다."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
