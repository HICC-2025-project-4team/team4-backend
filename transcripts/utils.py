# transcripts/utils.py

import cv2
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

# 1) OCR 엔진 초기화: Table 구조 분석 활성화
ocr_engine = PaddleOCR(
    lang='korean',
    use_angle_cls=True,
    #table=True,           # 테이블 구조 분석 모드
    # drop_score=0.1,     # 필요 시 인식 임계값 조절
)

def preprocess(image_path: str) -> np.ndarray:
    """
    OpenCV 기반 전처리:
    - 그레이스케일
    - 이진화 (Otsu)
    - 테이블 선(격자) 제거 (morphology open)
    - 색 반전 후 BGR 복원
    """
    # PIL로 로드(한글 경로 우회) → NumPy 배열
    pil = Image.open(image_path).convert('RGB')
    img = np.array(pil)

    # 1) 그레이스케일
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2) 이진화
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 3) 테이블 선 제거: 수평과 수직 선 모두 제거
    #    수평선 제거
    hor_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40,1))
    no_hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hor_kernel, iterations=1)
    #    수직선 제거
    ver_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1,40))
    no_ver = cv2.morphologyEx(no_hor, cv2.MORPH_OPEN, ver_kernel, iterations=1)

    # 4) 원본 이진화 이미지에서 선 부분만 마스킹
    cleaned = cv2.bitwise_xor(bw, no_ver)

    # 5) 색상 반전(배경=검정, 문자=흰색), BGR 채널로 복원
    inv = cv2.bitwise_not(cleaned)
    return cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR)


def parse_transcript_text(image_input) -> list[str]:
    """
    이미지에서 텍스트를 줄 단위로 추출합니다.

    - image_input: 
        1) 파일 경로 (str) 
        2) Django ImageField/FileField 인스턴스
    - 반환값: 텍스트 줄들의 리스트
    """
    # 1) PIL로 로드
    if isinstance(image_input, str):
        image_path = image_input
    else:
        image_path = image_input.path

    # 2) 전처리
    img_np = preprocess(image_input.path)

    # 3) OCR 수행
    ocr_results = ocr_engine.ocr(img_np)

    # 4) 텍스트 추출
    lines: list[str] = []
    for page in ocr_results:
        for entry in page:
            # entry = [박스좌표, (텍스트, 신뢰도), (선택적 추가정보)]
            if len(entry) >= 2:
                txt, score = entry[1]
                if score > 0.3:
                    lines.append(txt.strip())
    return lines

def extract_table_cells(image_path: str, debug: bool=False):
    """
    표 이미지에서 셀 하나하나의 bounding box 좌표와 잘린 이미지를 반환.
    Returns: List of tuples (row_idx, col_idx, cell_img_np)
    """
    # 1) 그레이스케일 + 이진화
    gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 2) 수평선, 수직선 검출
    horizontal = bw.copy()
    vertical   = bw.copy()
    cols = horizontal.shape[1]
    rows = vertical.shape[0]
    hor_size = cols // 30
    ver_size = rows // 30

    hor_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (hor_size, 1))
    ver_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, ver_size))
    horizontal = cv2.morphologyEx(horizontal, cv2.MORPH_OPEN, hor_kernel, iterations=1)
    vertical   = cv2.morphologyEx(vertical,   cv2.MORPH_OPEN, ver_kernel, iterations=1)

    # 3) 교차점 검출
    intersections = cv2.bitwise_and(horizontal, vertical)
    pts = cv2.findNonZero(intersections)  # Nx1x2 array
    pts = pts.reshape(-1, 2) if pts is not None else np.empty((0,2), int)

    # 4) unique한 행(y), 열(x) 좌표 클러스터링
    ys = sorted(set(pts[:,1]//20))  # 20px 단위로 묶기
    xs = sorted(set(pts[:,0]//20))
    row_lines = [int(y*20 + 10) for y in ys]
    col_lines = [int(x*20 + 10) for x in xs]

    cells = []
    # 5) 각 인접 교차점 사각형으로 셀 추출
    for i in range(len(row_lines)-1):
        for j in range(len(col_lines)-1):
            y1, y2 = row_lines[i],   row_lines[i+1]
            x1, x2 = col_lines[j],   col_lines[j+1]
            if y2-y1<10 or x2-x1<10:  # 너무 작으면 skip
                continue
            crop = cv2.cvtColor(gray[y1:y2, x1:x2], cv2.COLOR_GRAY2BGR)
            cells.append((i, j, crop))
            if debug:
                cv2.rectangle(gray, (x1,y1),(x2,y2),(128,128,128),1)

    if debug:
        cv2.imwrite("debug_cells.png", gray)
    return cells

def parse_transcript_table(image_input) -> list[list[str]]:
    """
    표 모드 대신 OpenCV 그리드 방식으로 표를 파싱합니다.
    Returns: 2D list of texts, including header row.
    """
    # 0) 파일 경로 획득
    if isinstance(image_input, str):
        path = image_input
    else:
        path = image_input.path

    # 1) 셀 추출
    cells = extract_table_cells(path)

    # 2) 셀별로 OCR 수행
    table_dict = {}  # {(row,col): text}
    for row_idx, col_idx, cell_img in cells:
        # 적당한 전처리도 섞어줄 수 있습니다.
        ocr_res = ocr_engine.ocr(np.array(cell_img), cls=True)
        text = ""
        # 첫 번째 페이지 첫 번째 entry만 따와 보기
        if ocr_res and ocr_res[0]:
            entry = ocr_res[0][0]
            if len(entry)>=2:
                txt, score = entry[1]
                if score>0.3:
                    text = txt.strip()
        table_dict[(row_idx, col_idx)] = text

    # 3) 2D 리스트로 변환 (최대 행·열 크기 계산)
    max_row = max(r for r,_ in table_dict.keys()) if table_dict else -1
    max_col = max(c for _,c in table_dict.keys()) if table_dict else -1
    table = []
    for i in range(max_row+1):
        row = []
        for j in range(max_col+1):
            row.append(table_dict.get((i,j), ""))
        table.append(row)

    return table