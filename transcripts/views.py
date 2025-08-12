# views.py
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status, permissions
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
import re

from .custom_paddle_ocr_script import rows_to_text
from .models import Transcript
from .serializers import (
    TranscriptUploadSerializer,
    TranscriptStatusSerializer,
    TranscriptParsedSerializer
)
from .tasks import process_transcript


def _rows_to_tsv(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(map(str, r)) for r in rows)


# ─────────────────────────────────────────────────────────────
# helpers: "2023학년도 1학년 2학기" / "1학년 2023학년도 1학기" → "1-2"
# ─────────────────────────────────────────────────────────────
def convert_term_to_semester(term_str: str) -> str:
    """
    '2023학년도 1학년 2학기' / '1학년 2023학년도 2학기' / '1학년 2학기' 등을 '1-2'로 변환.
    '학년도'의 '학년'에 잘못 매칭되지 않도록 (?!도)로 제외.
    """
    if not isinstance(term_str, str):
        return term_str

    g = re.search(r'(\d)\s*학년(?!도)', term_str)  # '학년도' 제외
    s = re.search(r'(\d)\s*학기', term_str)

    if g and s:
        return f"{g.group(1)}-{s.group(1)}"
    return term_str


def transform_parsed_records(data):
    """
    data가 [{'term': '...','code':...}, ...] 형태면
    term → semester('g-s')로 바꿔서 리스트 반환.
    그 외 포맷은 그대로 반환.
    """
    if isinstance(data, list) and data and isinstance(data[0], dict):
        out = []
        for item in data:
            # 원본을 건드리지 않도록 복사
            new_item = dict(item)
            if "term" in new_item:
                new_item["semester"] = convert_term_to_semester(new_item["term"])
                del new_item["term"]
            out.append(new_item)
        return out
    return data


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
            data={"files": request.data.getlist('files')},  # files를 리스트로 감싸서 전달
            context={'request': request}
        )
        if serializer.is_valid():
            transcript = serializer.save()
            process_transcript.delay(transcript.id)
            return Response(
                {"message": "업로드 완료", "status": "processing"},
                status=status.HTTP_201_CREATED
            )
        return Response(
            serializer.errors,
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
                status=status.HTTP_404_NOT_FOUND  # 명세에 따라 404 유지
            )

        data = transcript.parsed_data

        # 새 파이프라인: 2차원 rows로 저장된 경우 → 학기별 블록 텍스트로 반환
        if isinstance(data, list) and data and isinstance(data[0], list):
            return HttpResponse(
                rows_to_text(data, group_by_term=True),
                content_type="text/plain; charset=utf-8"
            )

        # 문자열이면 그대로 반환
        if isinstance(data, str):
            return HttpResponse(data, content_type="text/plain; charset=utf-8")

        # 과거 포맷: [{'term':..., ...}, ...] → 'semester'로 변환해서 JSON 반환
        data = transform_parsed_records(data)
        return Response(data, status=status.HTTP_200_OK)
