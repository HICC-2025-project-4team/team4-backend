import re
from collections import OrderedDict, defaultdict
from paddleocr import PaddleOCR
import cv2
import numpy as np
import os

# --- 상수 및 정규식 정의 ---
FOOTERS = {"신청학점", "전체성적", "취득학점", "증명평점", "백점만점환산점수", "평점", "평균", "이수구분"}
_TERM_ANY = re.compile(r'(?P<y>\d{4})\s*학년도.*?(?P<g>\d)\s*학년.*?(?P<s>\d)\s*학기')
PLUS_CANDS = {"+", "＋", "﹢", "十", "†", "ᐩ", "t", "T"}
ZERO_CANDS = {"0", "O", "〇", "○", "◯"}

# --- 이미지 전처리 ---
def _preprocess_image_for_ocr(img_path: str):
    image = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale_factor = 2
    resized = cv2.resize(gray, (int(gray.shape[1] * scale_factor), int(gray.shape[0] * scale_factor)), interpolation=cv2.INTER_CUBIC)
    _, binary_image = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return binary_image

# --- OCR 엔진 클래스 ---
class MyPaddleOCR:
    def __init__(self, lang: str="korean", min_score: float=0.15, **kwargs):
        self.lang = lang
        self.min_score = float(min_score)
        self._ocr = PaddleOCR(lang=self.lang, use_angle_cls=True, table=True, drop_score=0.1, det_db_box_thresh=0.3, det_db_unclip_ratio=1.6, **kwargs)

    def run_ocr(self, image_input) -> list[dict]: # 이미지 경로 또는 객체를 받을 수 있도록 수정
        result = self._ocr.ocr(image_input, cls=True)
        ocr_result = result[0] if result and isinstance(result, list) else []
        
        items = []
        # 이미지 크기에 따라 좌표를 재조정할 필요가 있을 수 있으므로, 크기를 함께 반환
        height, width = image_input.shape[:2] if isinstance(image_input, np.ndarray) else (0,0)

        for poly, (txt, score) in ocr_result:
            if score is not None and score < self.min_score: continue
            x_coords = [p[0] for p in poly]; y_coords = [p[1] for p in poly]
            bbox = (min(x_coords), min(y_coords), max(x_coords), max(y_coords))
            cx = (bbox[0] + bbox[2]) / 2.0; cy = (bbox[1] + bbox[3]) / 2.0; h = bbox[3] - bbox[1]
            items.append({"txt": txt.strip(), "bbox": bbox, "cx": cx, "cy": cy, "h": h})
        return items, (width, height)

ocr = MyPaddleOCR(min_score=0.15)

# --- 헬퍼 함수 ---
def _as_code(tok: str) -> str | None:
    s = tok.strip().upper().replace('O','0').replace('I','1').replace('L','1').replace('G','6')
    return s if re.fullmatch(r'\d{6}', s) else None

def _extract_grade_from_tokens(tokens: list[str]) -> str | None:
    if not tokens: return None
    text = "".join(tokens).upper().replace(" ", "")
    for char in PLUS_CANDS: text = text.replace(char, "+")
    for char in ZERO_CANDS: text = text.replace(char, "0")
    perfect_match = re.search(r"([ABCDF])([+0])", text)
    if perfect_match: return perfect_match.group(0)
    if "P" in text: return "P"
    single_char_match = re.search(r"([ABCDF])", text)
    if single_char_match: return single_char_match.group(1) + "+"
    return None

def _extract_retake_from_tokens(tokens: list[str]) -> bool:
    s = "".join(tokens).replace(' ', '')
    return '재수강' in s or 'Y' in s

def _match_header_key(txt: str) -> str | None:
    s = re.sub(r'\s+', '', txt)
    if '학수' in s and ('번' in s or '번호' in s): return '학수번호'
    if '성적' in s: return '성적'
    return None

def _find_term_text_by_header(items: list[dict], header_y: float) -> str:
    band = [it for it in items if (header_y - 200) <= it["cy"] <= (header_y - 6)]
    if not band: return ""
    band.sort(key=lambda d: (d["cy"], d["cx"]))
    return " ".join(it["txt"] for it in band).strip()

def _parse_semester(term_str: str) -> str:
    if not term_str: return "기타"
    m = re.search(r'(\d)\s*학년(?!도).*?(\d)\s*학기', term_str)
    if m: return f"{m.group(1)}-{m.group(2)}"
    return "기타"

# --- 메인 파싱 로직 ---
def ocr_single_table_term_code_grade_retake(image_path: str) -> list[dict]:
    # 1. 1차 스캔: 원본 이미지로 헤더와 학기 정보 확보
    original_image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    original_items, _ = ocr.run_ocr(original_image)
    if not original_items: return []

    headers = {key: it for it in original_items if (key := _match_header_key(it["txt"]))}
    if not ('학수번호' in headers and '성적' in headers):
        print("Warning: Table headers not found on original image.")
        return []

    header_y = (headers['학수번호']['cy'] + headers['성적']['cy']) / 2
    term_text = _find_term_text_by_header(original_items, header_y)
    current_semester = _parse_semester(term_text)

    # 2. 2차 스캔: 전처리된 이미지로 세부 내용(성적 등) 확보
    processed_image = _preprocess_image_for_ocr(image_path)
    processed_items, (proc_w, proc_h) = ocr.run_ocr(processed_image)
    
    # 전처리로 크기가 변경되었으므로, 좌표를 원본 기준으로 재조정
    orig_h, orig_w = original_image.shape[:2]
    scale_x, scale_y = orig_w / proc_w, orig_h / proc_h
    for item in processed_items:
        item['cx'] *= scale_x; item['cy'] *= scale_y
        bbox = item['bbox']
        item['bbox'] = (bbox[0]*scale_x, bbox[1]*scale_y, bbox[2]*scale_x, bbox[3]*scale_y)
        item['h'] *= scale_y

    # 3. 행(Row)으로 그룹화 (전처리된 아이템 기준)
    processed_items.sort(key=lambda d: (d["cy"], d["cx"]))
    rows_of_items = []
    if processed_items:
        data_items = [it for it in processed_items if it['cy'] > header_y]
        if data_items:
            current_row = [data_items[0]]
            for i in range(1, len(data_items)):
                if abs(data_items[i]['cy'] - current_row[-1]['cy']) < data_items[i]['h'] * 0.7:
                    current_row.append(data_items[i])
                else:
                    rows_of_items.append(current_row); current_row = [data_items[i]]
            rows_of_items.append(current_row)

    # 4. 헤더 X좌표(원본 기준)로 각 열의 텍스트(전처리된 결과) 추출
    col_x_code = headers['학수번호']['cx']
    col_x_grade = headers['성적']['cx']
    courses = []
    for row in rows_of_items:
        code_toks = [it['txt'] for it in row if abs(it['cx'] - col_x_code) < 50]
        grade_toks = [it['txt'] for it in row if abs(it['cx'] - col_x_grade) < 70]
        
        code = next((c for c in (_as_code(t) for t in code_toks) if c), None)
        if not code:
            code = next((c for c in (_as_code(it['txt']) for it in row) if c), None)
            if not code: continue

        grade = _extract_grade_from_tokens(grade_toks) or _extract_grade_from_tokens([it['txt'] for it in row])
        retake = _extract_retake_from_tokens([it['txt'] for it in row])

        courses.append({
            "code": code,
            "grade": grade or "",
            "retake": retake,
            "semester": current_semester,
        })
        
    return courses

# --- 최종 출력 포맷터 ---
def rows_to_text(courses: list[dict], group_by_term: bool = True) -> str:
    """디버깅 및 간단한 테스트를 위한 텍스트 변환 함수"""
    if not courses: return "파싱된 데이터가 없습니다."

    if not group_by_term:
        lines = []
        for c in courses:
            parts = [c.get('semester',''), c.get('code',''), c.get('grade',''), '재수강' if c.get('retake') else '']
            lines.append(" ".join(filter(None, parts)).strip())
        return "\n".join(lines)

    grouped = defaultdict(list)
    for c in courses:
        grouped[c.get('semester', '기타')].append(c)

    def semester_sort_key(sem):
        try:
            year, term = map(int, str(sem).split('-'))
            return (year, term)
        except (ValueError, IndexError): return (99, 9)
    
    sorted_semesters = sorted(grouped.keys(), key=semester_sort_key)

    blocks = []
    for semester in sorted_semesters:
        lines = [f"--- {semester} 학기 ---"]
        for c in grouped[semester]:
            parts = [c.get('code',''), c.get('grade',''), '재수강' if c.get('retake') else '']
            lines.append(" ".join(filter(None, parts)).strip())
        blocks.append("\n".join(lines))
        
    return "\n\n".join(blocks)