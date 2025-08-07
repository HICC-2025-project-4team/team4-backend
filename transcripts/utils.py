from .custom_paddle_ocr_script import ocr_to_cells


def parse_transcript_table_with_paddle(image_input, cols: int = 6) -> list[list[str]]:
    """
    Use MyPaddleOCR pipeline to parse tables into rows of text cells.
    """
    if isinstance(image_input, str):
        path = image_input
    else:
        path = image_input.path
    return ocr_to_cells(path, cols=cols)