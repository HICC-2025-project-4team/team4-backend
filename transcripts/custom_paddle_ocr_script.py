# transcripts/custom_paddle_ocr_script.py
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
            table=True,                # 테이블 구조 인식(추후 확장용)
            drop_score=0.1,
            det_db_box_thresh=0.3,
            det_db_unclip_ratio=1.6,
            **kwargs
        )
        self.img_path = None
        self.ocr_result: list = []

    def get_ocr_result(self):
        return self.ocr_result

    def get_img_path(self):
        return self.img_path

    def run_ocr(self, img_path: str, debug: bool = False) -> list[str]:
        """이미지에서 토큰(단어) 리스트만 뽑아온다."""
        self.img_path = img_path
        texts: list[str] = []
        result = self._ocr.ocr(img_path, cls=True)

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
    """보수적 보정: 괄호/기호/성적/학점/코드만 정리, 영문단어는 건드리지 않음."""
    t = t.strip()
    # 괄호/특수문자 정리
    t = (t.replace('［', '[').replace('］', ']')
           .replace('（', '(').replace('）', ')')
           .replace('[', '(').replace(']', ')')
           .replace('＊', '*'))

    # 성적 보정: A/B/C/D/F(+/0 생략 허용)
    m = re.fullmatch(r'([ABCDF])([+0]?)', t, re.IGNORECASE)
    if m:
        base = m.group(1).upper()
        suf = m.group(2)
        return base + ('+' if suf == '+' else '0')

    # 학점(1자리)만 보정: N→2, M→3
    if re.fullmatch(r'[0-9]', t) or t in {'N', 'M'}:
        return {'N': '2', 'M': '3'}.get(t, t)

    # 과목코드(6자리)
    if re.fullmatch(r'\d{6}', t):
        return t

    return t  # 나머지는 그대로


def _is_koreanish(tok: str) -> bool:
    """한글/국문 과목명 토큰 여부(괄호/별표 포함 허용)."""
    return bool(re.search(r'[가-힣]|[()＊*·&]', tok))


def _as_credit(tok: str) -> str | None:
    return tok if re.fullmatch(r'\d', tok) else None


def _as_grade(tok: str) -> str | None:
    t = tok.upper()
    if t in {'A+', 'B+', 'C+', 'D+', 'F+', 'A0', 'B0', 'C0', 'D0', 'F0', 'A', 'B', 'C', 'D', 'F'}:
        return 'A+' if t == 'A+' else (t if len(t) == 2 else t + '0')
    return None


def parse_transcript_tokens(tokens: list[str]) -> list[list[str]]:
    """
    성적표 토큰을 행렬 형태로 변환.
    반환 형식: [제목행, 헤더행(5열), 데이터행들(5열=학수번호/과목명/학점/성적/재수강)]
    """
    if not tokens:
        return []

    tokens = [_normalize_token(t) for t in tokens]

    # 1) 제목: "학수번호" 전까지
    try:
        head_idx = tokens.index("학수번호")
    except ValueError:
        head_idx = 0  # 못 찾으면 그냥 0

    title = tokens[:head_idx] if head_idx > 0 else []

    # 2) 헤더 고정(영문과목명 제거)
    headers = ["학수번호", "과목명", "학점", "성적", "재수강"]

    # 3) 데이터 시작 위치: 헤더 이후 첫 과목코드(6자리)까지 스킵
    i = head_idx
    while i < len(tokens) and not re.fullmatch(r'\d{6}', tokens[i]):
        i += 1

    rows: list[list[str]] = []
    while i < len(tokens):
        # 푸터 만나면 종료
        if tokens[i] in FOOTERS:
            break

        # 과목코드
        if not re.fullmatch(r'\d{6}', tokens[i] or ""):
            i += 1
            continue
        code = tokens[i]
        i += 1

        # 국문 과목명: 연속된 한국어 토큰을 모두 합쳐서 캡쳐
        kor_parts: list[str] = []
        while i < len(tokens) and _is_koreanish(tokens[i]) and not re.fullmatch(r'\d{6}', tokens[i]):
            kor_parts.append(tokens[i])
            i += 1
        if not kor_parts:  # 최소 1토큰은 있어야 함
            # 국문명이 누락된 경우 안전장치
            kor_parts = [""]

        kor = " ".join(kor_parts).strip()

        # 재수강 표식은 영문/학점/성적 앞뒤로 섞여 있을 수 있어 미리/사후 모두 체크
        re_flag = ""

        # (A) 영문 과목명은 건너뛰기: 학점/성적/다음 코드/푸터가 나올 때까지 스킵
        while i < len(tokens):
            if tokens[i] in FOOTERS:
                break
            if re.fullmatch(r'\d{6}', tokens[i]):  # 다음 과목 시작
                break
            # 재수강 N/Y 가 먼저 나오는 케이스 (예: "LAB DESIGN N A0")
            if tokens[i] in {"N", "Y"}:
                re_flag = tokens[i]
                i += 1
                continue
            # 학점/성적 등장 시 종료
            if _as_credit(tokens[i]) or _as_grade(tokens[i]):
                break
            i += 1  # 영문 토큰 스킵

        # (B) 학점/성적 캡쳐(순서 유연)
        credit, grade = "", ""
        if i < len(tokens) and _as_credit(tokens[i]):
            credit = _as_credit(tokens[i]) or ""
            i += 1
        if i < len(tokens) and _as_grade(tokens[i]):
            grade = _as_grade(tokens[i]) or ""
            i += 1
        # 반대 순서 보완
        if not credit and i < len(tokens) and _as_credit(tokens[i]):
            credit = _as_credit(tokens[i]) or ""
            i += 1
        if not grade and i < len(tokens) and _as_grade(tokens[i]):
            grade = _as_grade(tokens[i]) or ""
            i += 1

        # (C) 재수강 표식이 뒤에 오는 경우
        if not re_flag and i < len(tokens) and tokens[i] in {"N", "Y"}:
            re_flag = tokens[i]
            i += 1

        rows.append([code, kor, credit, grade, re_flag])

        # 다음 과목코드가 나올 때까지 쓸모없는 토큰 스킵
        while i < len(tokens) and not re.fullmatch(r'\d{6}', tokens[i]) and tokens[i] not in FOOTERS:
            i += 1

    result: list[list[str]] = []
    if title:
        result.append(title)
    result.append(headers)
    result.extend(rows)
    return result


# -----------------------------
# 사용 예시 함수
# -----------------------------

ocr = MyPaddleOCR()

def ocr_to_rows(image_path: str, cols: int = 6) -> list[list[str]]:
    tokens = ocr.run_ocr(image_path, debug=False)
    table = parse_transcript_tokens(tokens)
    return table


def rows_to_text(rows: list[list[str]], include_english: bool = True) -> str:
    """
    [제목행, 헤더행, 데이터행...]을 탭(\t) 구분 멀티라인 문자열로 변환.
    - 헤더/데이터 칼럼 수에 자동 적응(5열이면 그대로 출력).
    - include_english는 하위호환용(현재 파서는 영문 칼럼을 생성하지 않음).
    """
    if not rows:
        return ""

    lines: list[str] = []

    # 제목(있을 때만)
    if len(rows) >= 1 and rows[0] and "학수번호" not in rows[0]:
        lines.append("\t".join(rows[0]))

    # 헤더
    if len(rows) >= 2:
        lines.append("\t".join(rows[1]))

    # 데이터
    for r in rows[2:]:
        lines.append("\t".join(r))

    return "\n".join(lines)
