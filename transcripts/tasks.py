import os
from celery import shared_task
from django.conf import settings
from .models import Transcript
from paddleocr import PaddleOCR
from PIL import Image

# OCR 모델 초기화 (앱 로딩 시 한 번만)
ocr = PaddleOCR(
    use_angle_cls=True,
    lang='korean',            # 한국어 + 영어 텍스트 인식
    enable_mkldnn=True    # CPU 최적화 (옵션)
)

@shared_task
def process_transcript_ocr(transcript_id):
    tr = Transcript.objects.get(id=transcript_id)
    tr.status = 'PROCESSING'
    tr.save(update_fields=['status'])

    try:
        # 1) 파일 경로 얻기 & Pillow로 열기
        file_path = tr.file.path
        image = Image.open(file_path).convert('RGB')

        # 2) OCR 수행
        ocr_results = ocr.ocr(file_path, cls=True)

        # 3) 결과 추출 및 간단 파싱
        lines = []
        for page in ocr_results:
            for line in page:
                # line == [ [x1,y1], ... ], (text, confidence)
                text, _score = line[1]
                lines.append(text)

        # 4) 정규식으로 “과목명/학점/학기/구분” 파싱
        import re
        parsed = []
        pattern = re.compile(r'(.+?)\s*([0-9]\.?[0-9]?)학점\s*(\d{4}-\d)\s*(전공필수|전공선택|교양필수|교양선택)')
        for txt in lines:
            m = pattern.search(txt)
            if m:
                subject, credit, semester, category = m.groups()
                parsed.append({
                    'subject':   subject.strip(),
                    'credit':    float(credit),
                    'semester':  semester,
                    'category':  category
                })

        # 5) 저장
        tr.parsed = parsed
        tr.status = 'DONE'
        tr.error_message = ''
        tr.save(update_fields=['parsed', 'status', 'error_message'])

    except Exception as e:
        tr.status = 'ERROR'
        tr.error_message = str(e)
        tr.save(update_fields=['status', 'error_message'])
