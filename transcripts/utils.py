# transcripts/utils.py

import os
from paddleocr import PaddleOCR

# OCR 엔진 초기화 (예시)
ocr_engine = PaddleOCR(lang='korean', use_angle_cls=True)

def run_ocr(image_path: str) -> str:
    """
    이미지 파일 경로를 받아서 OCR로 텍스트(raw string)를 반환합니다.
    """
    # PaddleOCR 결과에서 텍스트만 추출
    result = ocr_engine.ocr(image_path, cls=True)
    lines = [line[1][0] for line in result[0]]  # 페이지당 첫 번째 블록 기준
    return '\n'.join(lines)

import re

def parse_text(text: str) -> dict:
    """
    OCR로 뽑은 원시 텍스트를 분석해서
    {'courses': [ {'name':…, 'credit':…, 'semester':…, 'type':…}, … ] }
    형태의 딕셔너리로 반환합니다.
    """
    courses = []
    # 예시 정규식: 과목명, 학점, 학기, 이수구분
    pattern = re.compile(r'(?P<name>\S+)\s+(?P<credit>\d+)\s+(?P<semester>\d{4}-[12])\s+(?P<type>\S+)')
    for line in text.splitlines():
        m = pattern.search(line)
        if m:
            courses.append({
                'name': m.group('name'),
                'credit': int(m.group('credit')),
                'semester': m.group('semester'),
                'type': m.group('type')
            })
    return {'courses': courses}
