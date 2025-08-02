# tasks.py
from celery import shared_task
from django.conf import settings
from .utils import parse_transcript_table
from .models import Transcript    # 실제 모델 이름에 맞춰 변경하세요

@shared_task
def process_transcript(transcript_id: int) -> list[str]:
    """
    1) DB에서 Transcript 인스턴스를 조회
    2) status='PROCESSING' 저장
    3) image Field에서 OCR 수행
    4) parsed_text, status='DONE' 저장
    """
    try:
        t = Transcript.objects.get(pk=transcript_id)
    except Transcript.DoesNotExist:
        print(f"[OCR 태스크] Transcript #{transcript_id} 가 존재하지 않습니다.")
        return []

    # → 2) 처리 중 표시
    t.status = Transcript.STATUS.processing
    t.save(update_fields=["status"])

    # → 3) OCR 수행
    print(f"[OCR 태스크] 시작: Transcript #{transcript_id}, 파일={t.file.name}")
    all_pages = []
    for page in t.pages.order_by('page_number'):
        table = parse_transcript_table(page.file)
        all_pages.append({
            "page": page.page_number,
            "table": table
        })

    # → 4) 결과 및 완료 상태 저장
    t.parsed_data = all_pages
    t.status = Transcript.STATUS.done
    t.save(update_fields=["parsed_data", "status", "error_message"])

    return table