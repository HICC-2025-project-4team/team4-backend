from celery import shared_task
from .models import Transcript

@shared_task
def process_transcript(transcript_id):
    transcript = Transcript.objects.get(id=transcript_id)
    try:
        # 1) 이미지 전처리 (흑백·노이즈 제거)  
        # 2) OCR 수행 (PaddleOCR 등)  
        # 3) 정규식으로 과목명/학점/학기/이수구분 파싱  
        parsed = {
            "courses": [
                {"name": "컴퓨터구조", "credit": 3, "semester": "2025-1", "type": "전공필수"},
                {"name": "글쓰기",     "credit": 2, "semester": "2025-1", "type": "교양필수"},
                # …
            ]
        }
        transcript.parsed_data = parsed
        transcript.status = 'completed'
        transcript.save()
    except Exception as e:
        transcript.status = 'error'
        transcript.error_message = str(e)
        transcript.save()
