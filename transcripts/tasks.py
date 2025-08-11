# transcripts/tasks.py

from celery import shared_task
from .utils import parse_single_table_with_paddle
from .models import Transcript

@shared_task
def process_transcript(transcript_id: int):
    try:
        t = Transcript.objects.get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return

    # 상태 → 처리중
    t.status = Transcript.STATUS.processing
    t.save(update_fields=["status"])

    try:
        all_rows: list[list[str]] = []

        # 1) 페이지별로 표 파싱 → 셀 단위 문자열 수집
        for page in t.pages.order_by("page_number"):
            print(f"[OCR 태스크] 페이지 {page.page_number} 처리 시작: {page.file.name}")
            rows = parse_single_table_with_paddle(page.file)
            all_rows.extend(rows)

        # 2) 최종적으로 flat list를 JSONField에 저장
        t.parsed_data   = all_rows
        t.status        = Transcript.STATUS.done
        t.error_message = None

    except Exception as e:
        print(f"Transcript processing failed for id={transcript_id}: {e}")
        t.status        = Transcript.STATUS.error
        t.error_message = str(e)

    finally:
        t.save(update_fields=["parsed_data", "status", "error_message"])

    return t.status