import re
import cv2
from collections import OrderedDict, defaultdict
from paddleocr import PaddleOCR

# --- 상수 및 정규식 정의 ---
FOOTERS = {
    "신청학점", "전체성적", "취득학점", "증명평점", "백점만점환산점수",
    "평점", "평균", "이수구분"
}
_TERM_ANY = re.compile(r'(?P<y>\d{4})\s*학년도.*?(?P<g>\d)\s*학년.*?(?P<s>\d)\s*학기')
PLUS_CANDS = {"+", "＋", "﹢", "十", "†", "ᐩ"}
ZERO_CANDS = {"0", "O", "〇", "○", "◯"}

# --- OCR 엔진 클래스 ---
class MyPaddleOCR:
    def __init__(self, lang: str="korean", min_score: float=0.15, **kwargs):
        self.lang = lang
        self.min_score = float(min_score)
        self._ocr = PaddleOCR(
            lang=self.lang, use_angle_cls=True, table=True, drop_score=0.1,
            det_db_box_thresh=0.3, det_db_unclip_ratio=1.6, **kwargs
        )
        self.img_path: str | None = None
        self.ocr_result: list = []

    def run_ocr(self, img_path: str, debug: bool=False) -> list[dict]:
        self.img_path = img_path
        result = self._ocr.ocr(img_path, cls=True)
        self.ocr_result = result[0] if result and isinstance(result, list) else []
        
        items = []
        for poly, (txt, score) in self.ocr_result:
            if score is not None and score < self.min_score: continue
            x_coords = [p[0] for p in poly]
            y_coords = [p[1] for p in poly]
            bbox = (min(x_coords), min(y_coords), max(x_coords), max(y_coords))
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            h = bbox[3] - bbox[1]
            items.append({"txt": txt.strip(), "bbox": bbox, "cx": cx, "cy": cy, "h": h})
        return items

ocr = MyPaddleOCR(min_score=0.15)

# --- 헬퍼 함수 ---
def _as_code(tok: str) -> str | None:
    s = tok.strip().upper().replace('O','0').replace('I','1').replace('L','1').replace('G','g')
    return s if re.fullmatch(r'\d{5,6}g?', s) or re.fullmatch(r'\d{6}', s) else None

def _as_grade(tok: str) -> str | None:
    t = tok.upper().replace('O','0')
    for p in PLUS_CANDS: t = t.replace(p, '+')
    if t in {'A+','B+','C+','D+','F+','A0','B0','C0','D0','F0', 'P'}: return t
    return None

def _extract_grade_from_tokens(tokens: list[str]) -> str | None:
    if not tokens: return None
    norm_tokens = [t.strip().upper() for t in tokens if t.strip()]
    if not norm_tokens: return None

    for t in norm_tokens:
        grade = _as_grade(t)
        if grade: return grade

    for i in range(len(norm_tokens) - 1):
        current_tok = norm_tokens[i]
        next_tok = norm_tokens[i+1]
        if current_tok in {'A', 'B', 'C', 'D', 'F'}:
            if any(p in next_tok for p in PLUS_CANDS): return current_tok + "+"
            if any(z in next_tok for z in ZERO_CANDS): return current_tok + "0"

    for t in norm_tokens:
        if t in {'A', 'B', 'C', 'D', 'F'}: return t + '0'
    
    return None

def _extract_retake_from_tokens(tokens: list[str]) -> bool:
    s = "".join(tokens).replace(' ', '')
    return '재수강' in s or 'Y' in s

def _match_header_key(txt: str) -> str | None:
    s = re.sub(r'\s+', '', txt)
    if '학수' in s and ('번' in s or '번호' in s): return '학수번호'
    if '성적' in s: return '성적'
    if '재수' in s and '강' in s: return '재수강'
    return None

def _find_term_text(items: list[dict], header_y: float, x_left: float, x_right: float) -> str:
    band = [it for it in items if (header_y - 200) <= it["cy"] <= (header_y - 6)]
    if not band: return ""
    band.sort(key=lambda d: (d["cy"], d["cx"]))
    line = " ".join(it["txt"] for it in band)
    m = _TERM_ANY.search(line)
    return f"{m.group('y')}학년도 {m.group('g')}학년 {m.group('s')}학기" if m else line.strip()

# --- 메인 파싱 로직 (완전히 새로 작성됨) ---
def ocr_single_table_term_code_grade_retake(image_path: str) -> list[dict]:
    items = ocr.run_ocr(image_path)
    if not items:
        return []

    # 1. 헤더 찾기 (필수: 학수번호, 성적)
    h_code, h_grade, h_retake = None, None, None
    potential_headers = [it for it in items if it['h'] < 80] # 너무 큰 텍스트는 헤더가 아님
    for it in potential_headers:
        key = _match_header_key(it["txt"])
        if key == '학수번호': h_code = it
        elif key == '성적': h_grade = it
        elif key == '재수강': h_retake = it
    
    # 필수 헤더가 없으면 테이블 분석 불가, 빈 결과 반환
    if not h_code or not h_grade:
        return []

    # 2. 헤더 위치를 기반으로 열(Column) 경계 정의
    header_y = (h_code['cy'] + h_grade['cy']) / 2
    col_x_code = h_code['cx']
    col_x_grade = h_grade['cx']
    col_x_retake = h_retake['cx'] if h_retake else float('inf')

    # 3. 학기 정보 찾기
    term_text = _find_term_text(items, header_y, h_code['bbox'][0], h_grade['bbox'][2])

    # 4. 데이터 영역의 아이템들을 행(Row)으로 그룹화
    data_items = [it for it in items if it['cy'] > header_y + 15 and it['txt'] not in FOOTERS]
    data_items.sort(key=lambda d: (d["cy"], d["cx"]))
    
    rows_of_items = []
    if data_items:
        current_row = [data_items[0]]
        for i in range(1, len(data_items)):
            # y좌표가 비슷하면 같은 행으로 간주
            if abs(data_items[i]['cy'] - current_row[-1]['cy']) < data_items[i]['h'] * 0.7:
                current_row.append(data_items[i])
            else:
                rows_of_items.append(current_row)
                current_row = [data_items[i]]
        rows_of_items.append(current_row)

    # 5. 각 행을 분석하여 최종 데이터 추출
    results = []
    for row in rows_of_items:
        code_toks = [it['txt'] for it in row if abs(it['cx'] - col_x_code) < 50]
        grade_toks = [it['txt'] for it in row if abs(it['cx'] - col_x_grade) < 50]
        retake_toks = [it['txt'] for it in row if abs(it['cx'] - col_x_retake) < 50]

        code = next((c for c in (_as_code(t) for t in code_toks) if c), None)
        
        # 행에 학수번호가 없으면 유효한 데이터 행이 아님
        if not code:
            # 열 탐색에 실패한 경우, 행 전체에서 다시 탐색
            code = next((c for c in (_as_code(it['txt']) for it in row) if c), None)
            if not code:
                continue

        grade = _extract_grade_from_tokens(grade_toks)
        if not grade: # 성적 열에서 못찾으면 행 전체에서 다시 탐색
            grade = _extract_grade_from_tokens([it['txt'] for it in row])
        
        retake = _extract_retake_from_tokens(retake_toks)
        if not retake: # 재수강 열에서 못찾으면 행 전체에서 다시 탐색
             retake = _extract_retake_from_tokens([it['txt'] for it in row])

        results.append({
            "term": term_text,
            "code": code,
            "grade": grade or "",
            "retake": retake
        })
        
    return results

# --- 최종 출력 포맷터 ---
def rows_to_text(courses: list[dict], group_by_term: bool = True) -> str:
    if not courses: return "파싱된 데이터가 없습니다."

    if not group_by_term:
        lines = []
        for c in courses:
            parts = [c.get('term',''), c.get('code',''), c.get('grade',''), '재수강' if c.get('retake') else '']
            lines.append(" ".join(filter(None, parts)).strip())
        return "\n".join(lines)

    grouped = defaultdict(list)
    for c in courses:
        grouped[c.get('term', '미상 학기')].append(c)

    blocks = []
    for term, term_courses in grouped.items():
        lines = [term, "학수번호 성적 재수강"]
        for c in term_courses:
            parts = [c.get('code',''), c.get('grade',''), '재수강' if c.get('retake') else '']
            lines.append(" ".join(filter(None, parts)).strip())
        blocks.append("\n".join(lines))
        
    return "\n\n".join(blocks)