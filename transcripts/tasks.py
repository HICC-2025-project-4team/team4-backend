from celery import shared_task
from .models import Transcript
from .utils import run_ocr, parse_text  # 예시 유틸 함수

@shared_task
def process_transcript(transcript_id):
    tr = Transcript.objects.get(id=transcript_id)
    seen = set()
    results = []

    # 페이지별로 순서대로 OCR + 파싱
    for page in tr.pages.order_by('page_number'):
        text = run_ocr(page.file.path)
        parsed = parse_text(text)  # {'courses': [ {...}, ... ]}
        for course in parsed.get('courses', []):
            key = f"{course['name']}_{course['credit']}_{course['semester']}"
            if key not in seen:
                seen.add(key)
                results.append(course)

    tr.parsed_data = {'courses': results}
    tr.status = 'DONE'
    tr.save()