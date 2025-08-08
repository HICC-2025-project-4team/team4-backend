import re
import cv2
from paddleocr import PaddleOCR, draw_ocr


FOOTERS = {"신청학점", "전체성적", "취득학점", "증명평점", "백점만점환산점수"}
class MyPaddleOCR:
    def __init__(self, lang: str = "korean", **kwargs):
        self.lang = lang
        self._ocr = PaddleOCR(
            lang=self.lang,
            use_angle_cls=True,
            table=True,                # 테이블 구조 인식 활성화(지금은 토큰만 사용, 추후 확장용)
            drop_score=0.1,
            det_db_box_thresh=0.3,
            det_db_unclip_ratio=1.6,
            **kwargs
        )
        self.img_path = None
        self.ocr_result = []

    def get_ocr_result(self):
        return self.ocr_result

    def get_img_path(self):
        return self.img_path

    def run_ocr(self, img_path: str, debug: bool = False) -> list[str]:
        """이미지에서 토큰(단어) 리스트만 뽑아온다."""
        self.img_path = img_path
        texts = []
        result = self._ocr.ocr(img_path, cls=True)   # ← cls=True 권장

        # 일반(라인) 결과를 그대로 사용 (table=True여도 라인 결과는 유지됨)
        self.ocr_result = result[0] if isinstance(result, list) else result

        if self.ocr_result:
            for r in self.ocr_result:
                texts.append(r[1][0])   # (text, score) 중 text
        else:
            texts = []

        if debug:
            self.show_img_with_ocr()

        return texts

    def show_img_with_ocr(self, out_path: str | None = None):
        img = cv2.imread(self.img_path)
        roi_img = img.copy()
        for text_result in self.ocr_result:
            tlX, tlY = map(int, text_result[0][0])
            trX, trY = map(int, text_result[0][1])
            brX, brY = map(int, text_result[0][2])
            blX, blY = map(int, text_result[0][3])

            cv2.line(roi_img, (tlX, tlY), (trX, trY), (0, 255, 0), 2)
            cv2.line(roi_img, (trX, trY), (brX, brY), (0, 255, 0), 2)
            cv2.line(roi_img, (brX, brY), (blX, blY), (0, 255, 0), 2)
            cv2.line(roi_img, (blX, blY), (tlX, tlY), (0, 255, 0), 2)

        if out_path:
            cv2.imwrite(out_path, roi_img)

# -----------------------------
# 아래: 토큰 → 표 행 파서
# -----------------------------

def _normalize_token(t: str) -> str:
    """OCR 오인식 보정: O↔0, I↔1 등 기본 규칙"""
    t = t.replace('O', '0').replace('o', '0')
    t = t.replace('I', '1').replace('l', '1').replace('＊','*')
    # 학점/성적에서 BO, CO → B0, C0
    t = re.sub(r'^([ABCDF])O$', r'\g<1>0', t) 
    return t

def parse_transcript_tokens(tokens: list[str]) -> list[list[str]]:
    """
    성적표 토큰을 행렬 형태로 변환.
    [제목행, 헤더행, 데이터행들...] 순서의 2차원 리스트를 반환.
    """
    if not tokens:
        return []

    tokens = [_normalize_token(t) for t in tokens]

    # 1) 제목: "학수번호"가 나오기 전까지 (보통 3개: 2025학년도 3학년 1학기)
    try:
        head_idx = tokens.index("학수번호")
    except ValueError:
        head_idx = 0  # 못 찾으면 그냥 0

    title = tokens[:head_idx] if head_idx > 0 else []
    # 2) 헤더(열 제목): "학수번호"부터 6개 (학수번호/과목명/영문과목명/학점/성적/재수강)
    headers = tokens[head_idx:head_idx+6] if head_idx+6 <= len(tokens) else []

    rows = []
    i = head_idx + len(headers)
    # 3) 데이터 파싱: "6자리 숫자"를 학수번호로 보고 한 행을 생성
    while i < len(tokens):
        # 푸터(전체성적/신청학점 등) 만난 경우 종료
        if tokens[i] in ("신청학점", "전체성적", "취득학점", "증명평점", "백점만점환산점수"):
            break

        if not re.fullmatch(r'\d{6}', tokens[i] or ""):
            i += 1
            continue

        code = tokens[i]; i += 1
        if i >= len(tokens): break
        kor = tokens[i]; i += 1

        # 영문과목명: '학점'(정수) 나오기 전까지 붙이기
        eng_tokens = []
        while i < len(tokens) and not re.fullmatch(r'\d+', tokens[i] or ""):
            # 푸터 만나면 중단
            if tokens[i] in ("신청학점", "전체성적", "취득학점", "증명평점", "백점만점환산점수"):
                break
            eng_tokens.append(tokens[i])
            i += 1
        eng = " ".join(eng_tokens).replace("  ", " ").strip()

        if i >= len(tokens): break
        credit = tokens[i]; i += 1

        if i >= len(tokens): break
        grade = tokens[i]; i += 1

        rows.append([code, kor, eng, credit, grade])

    result = []
    if title:   result.append(title)
    if headers: result.append(headers)
    result.extend(rows)
    return result

# -----------------------------
# 사용 예시 함수 (원래 ocr_to_cells 대체)
# -----------------------------

ocr = MyPaddleOCR()

def ocr_to_rows(image_path: str, cols: int = 6) -> list[list[str]]:
    tokens = ocr.run_ocr(image_path, debug=False)
    table  = parse_transcript_tokens(tokens)
    return table


def rows_to_text(rows: list[list[str]]) -> str:
    """
    [제목행, 헤더행, 데이터행...] 형태의 rows를
    탭(\t)으로 구분한 멀티라인 문자열로 변환.
    """
    if not rows:
        return ""

    lines = []
    # 제목행(옵션), 헤더행(옵션)
    if len(rows) >= 1: lines.append("\t".join(rows[0]))
    if len(rows) >= 2: lines.append("\t".join(rows[1]))

    # 데이터행: [code, kor, eng, credit, grade] 5개로 패딩
    for r in rows[2:]:
        r5 = (r + ["", ""])[:5]
        lines.append("\t".join(r5))

    return "\n".join(lines)
