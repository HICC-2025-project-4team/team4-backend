# custom_paddle_ocr_script.py

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

# --- Debug 스위치 & 통계 출력 헬퍼 ---
DEBUG = True

def _print_score_stats(items, label=""):
    """run_ocr()가 반환한 dict 리스트에서 score 통계를 출력"""
    if not items:
        print(f"[{label}] no items"); return
    scores = [float(it.get("score", 0.0)) for it in items]
    print(f"[{label}] n={len(items)} avg={np.mean(scores):.3f} min={np.min(scores):.3f} max={np.max(scores):.3f}")

# --- 이미지 전처리 ---
def _preprocess_image_for_ocr(image_obj, sharpen=False, scale_factor=2):
    if len(image_obj.shape) == 3:
        gray = cv2.cvtColor(image_obj, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_obj

    if sharpen:
        blurred = cv2.GaussianBlur(gray, (0, 0), 3)
        sharpened = cv2.addWeighted(gray, 1.5, blurred, -0.5, 0)
    else:
        sharpened = gray

    if scale_factor > 1:
        resized = cv2.resize(
            sharpened,
            (int(gray.shape[1] * scale_factor), int(gray.shape[0] * scale_factor)),
            interpolation=cv2.INTER_CUBIC
        )
    else:
        resized = sharpened
    
    _, binary_image = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return binary_image

# --- OCR 엔진 클래스 ---
class MyPaddleOCR:
    def __init__(self, lang: str="korean", min_score: float=0.15, **kwargs):
        self.lang = lang
        self.min_score = float(min_score)
        self._ocr = PaddleOCR(
            lang=self.lang, use_angle_cls=True, table=True,
            drop_score=0.1, det_db_box_thresh=0.3, det_db_unclip_ratio=1.6, **kwargs
        )

    def run_ocr(self, image_input, preprocess_info=None) -> list[dict]:
        if preprocess_info:
            image_to_process = _preprocess_image_for_ocr(image_input, **preprocess_info)
        else:
            image_to_process = image_input

        result = self._ocr.ocr(image_to_process, cls=True)
        ocr_result = result[0] if result and isinstance(result, list) else []
        
        items = []
        for entry in ocr_result:
            try:
                poly, (txt, score) = entry
            except Exception:
                continue

            if score is not None and score < self.min_score:
                continue
            
            scale = preprocess_info.get('scale_factor', 1) if preprocess_info else 1
            try:
                scaled_poly = [(p[0] / scale, p[1] / scale) for p in poly]
            except Exception:
                continue
            
            x_coords = [p[0] for p in scaled_poly]; y_coords = [p[1] for p in scaled_poly]
            bbox = (min(x_coords), min(y_coords), max(x_coords), max(y_coords))
            cx = (bbox[0] + bbox[2]) / 2.0; cy = (bbox[1] + bbox[3]) / 2.0; h = bbox[3] - bbox[1]
            item = {"txt": txt.strip(), "bbox": bbox, "cx": cx, "cy": cy, "h": h,
                    "score": float(score) if score is not None else 0.0}
            items.append(item)

            if DEBUG:
                print(f"[OCR] '{item['txt']}' score={item['score']:.3f} "
                      f"bbox=({bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f})")
        return items

ocr = MyPaddleOCR(min_score=0.15)

# --- 헬퍼 함수 ---
def _find_code_in_tok(tok: str) -> str | None:
    s = tok.strip().upper().replace('O','0').replace('I','1').replace('L','1').replace('G','6')
    match = re.search(r'(\d{6})', s)
    return match.group(1) if match else None

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

def _parse_semester(term_str: str) -> str:
    if not term_str: return "기타"
    m = re.search(r'(\d)\s*학년(?!도).*?(\d)\s*학기', term_str)
    if m: return f"{m.group(1)}-{m.group(2)}"
    return "기타"

def _match_header_key(txt: str) -> str | None:
    s = re.sub(r'\s+', '', txt)
    if '학수' in s and ('번' in s or '번호' in s): return '학수번호'
    return None

# --- 메인 파싱 로직 ---
def ocr_single_table_term_code_grade_retake(image_path: str) -> list[dict]:
    original_image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if original_image is None:
        raise FileNotFoundError(f"이미지를 열 수 없습니다: {image_path}")
    
    # 1. 1차 스캔 (원본): 구조(학기, 헤더 위치) 파악
    original_items = ocr.run_ocr(original_image, preprocess_info=None)
    if DEBUG:
        _print_score_stats(original_items, "original/raw")
    if not original_items: return []

    full_text = " ".join(it['txt'] for it in original_items)
    term_match = _TERM_ANY.search(full_text)
    current_semester = _parse_semester(term_match.group(0)) if term_match else "기타"

    header = next((it for it in original_items if _match_header_key(it["txt"])), None)
    header_y = header['cy'] if header else 0

    # 2. 2차 스캔 (전처리): 내용(과목 전체) 파악
    processed_items = ocr.run_ocr(original_image, preprocess_info={'sharpen': True, 'scale_factor': 2})
    if DEBUG:
        _print_score_stats(processed_items, "processed/sharpen+scale2")

    # 3. 행(Row)으로 그룹화
    data_items = [it for it in processed_items if it['cy'] > header_y]
    rows = defaultdict(list)
    for item in data_items:
        rows[round(item['cy'] / 10)].append(item)
    
    courses = []
    # 4. 각 행을 분석하여 최종 데이터 추출
    for row_items in rows.values():
        row_items.sort(key=lambda x: x['cx'])
        
        code = None
        if header:
            col_x_code = header['cx']
            avg_y = sum(it['cy'] for it in row_items) / len(row_items)
            
            y_start, y_end = int(avg_y - 12), int(avg_y + 12)
            x_start, x_end = int(col_x_code - 40), int(col_x_code + 40)
            code_roi = original_image[y_start:y_end, x_start:x_end]
            
            if code_roi.size > 0:
                # 핀포인트 OCR
                pinpoint_items = ocr.run_ocr(code_roi, preprocess_info={'sharpen': True, 'scale_factor': 4})
                if DEBUG:
                    _print_score_stats(pinpoint_items, f"pinpoint/code y≈{avg_y:.1f}")
                if pinpoint_items:
                    code = _find_code_in_tok("".join(it['txt'] for it in pinpoint_items))

        # 핀포인트 실패 시, 기존 방식으로 다시 탐색
        if not code:
            code = _find_code_in_tok(" ".join(it['txt'] for it in row_items))

        if not code: 
            continue

        grade = _extract_grade_from_tokens([it['txt'] for it in row_items])
        retake = _extract_retake_from_tokens([it['txt'] for it in row_items])
        
        courses.append({
            "code": code,
            "grade": grade or "",
            "retake": retake,
            "semester": current_semester,
        })
        
    return courses

# --- 최종 출력 포맷터 ---
def rows_to_text(courses: list[dict], group_by_term: bool = True) -> str:
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
