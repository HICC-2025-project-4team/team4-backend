# utils.py
from .custom_paddle_ocr_script import ocr_single_table_term_code_grade_retake
import tempfile

def parse_single_table_with_paddle(image_input) -> list[list[str]]:
    if isinstance(image_input, str):
        path = image_input
    elif hasattr(image_input, "path"):             # FileField/TemporaryUploadedFile
        path = image_input.path
    else:                                          # InMemoryUploadedFile 등
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            image_input.seek(0)
            tmp.write(image_input.read())
            path = tmp.name
    return ocr_single_table_term_code_grade_retake(path)
