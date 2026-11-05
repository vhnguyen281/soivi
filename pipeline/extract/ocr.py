"""OCR helpers for PDFs whose text is drawn as small images (no text layer).

Built for strictness, not convenience: every value is read twice at different
resolutions and both reads must agree; callers also validate the result's format.
Any disagreement raises OcrDisagreement, which adapters turn into AdapterBroken.
"""

from collections.abc import Callable, Sequence
from typing import Any

import pytesseract
from PIL import Image, ImageOps

Box = tuple[float, float, float, float]  # x0, top, x1, bottom in PDF points

DIGITS = "0123456789."
RESOLUTIONS = (400, 600)


class OcrDisagreement(Exception):
    pass


def ocr_box(
    page: Any,
    box: Box,
    whitelist: str = DIGITS,
    psm: int = 7,
    extract: Callable[[str], str | None] = lambda text: text,
) -> str:
    """OCR one region of a pdfplumber page at two resolutions.

    `extract` pulls the value of interest out of each raw read (default: the whole
    text). The extracted values must be identical and not None.
    """
    values = []
    for resolution in RESOLUTIONS:
        image = _prepare(page.crop(_clip(page, box)).to_image(resolution=resolution).original)
        config = f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
        values.append(extract(pytesseract.image_to_string(image, config=config).strip()))
    if None in values or len(set(values)) != 1:
        raise OcrDisagreement(
            f"OCR reads disagree for box {tuple(round(v) for v in box)}: {values}"
        )
    return str(values[0])


def _prepare(image: Image.Image) -> Image.Image:
    """Black text on white: Otsu threshold, inverted when the text is the light part
    (header cells are white text on green)."""
    grey = image.convert("L")
    histogram = grey.histogram()
    threshold = _otsu(histogram)
    binary = grey.point(lambda v: 255 if v > threshold else 0)
    dark = sum(histogram[: threshold + 1])
    if dark > sum(histogram) / 2:  # background is the dark part
        binary = ImageOps.invert(binary)
    return binary


def _otsu(histogram: list[int]) -> int:
    total = sum(histogram)
    sum_all = sum(i * n for i, n in enumerate(histogram))
    best, best_var, weight_bg, sum_bg = 0, -1.0, 0, 0
    for t in range(256):
        weight_bg += histogram[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += t * histogram[t]
        mean_bg, mean_fg = sum_bg / weight_bg, (sum_all - sum_bg) / weight_fg
        between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if between > best_var:
            best, best_var = t, between
    return best


def image_boxes(page: Any, cell: Box) -> list[Box]:
    """Boxes of the images whose centre lies in `cell`, left to right, padded by 2pt.

    Text in these PDFs is placed as images; an image can stick out of its cell, so we
    crop by the image, never by the cell (cropping by cell once cut "5.99" to "5.95").
    """
    found = []
    for image in page.images:
        cx = (image["x0"] + image["x1"]) / 2
        cy = (image["top"] + image["bottom"]) / 2
        if cell[0] <= cx <= cell[2] and cell[1] <= cy <= cell[3]:
            found.append((image["x0"] - 2, image["top"] - 2, image["x1"] + 2, image["bottom"] + 2))
    return sorted(found)


def union(boxes: Sequence[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _clip(page: Any, box: Box) -> Box:
    x0, top, x1, bottom = page.bbox
    return (max(box[0], x0), max(box[1], top), min(box[2], x1), min(box[3], bottom))
