import time
from pathlib import Path

from markitdown import MarkItDown

from txt_parser import read

MARKITDOWN_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".html", ".htm", ".csv", ".json", ".xml",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
    ".epub", ".zip",
}

_md = MarkItDown()


def parse(filepath: str | Path) -> tuple[str, float]:
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    t0 = time.perf_counter()

    if ext in MARKITDOWN_EXTENSIONS:
        result = _md.convert(str(filepath))
        text = result.text_content
    else:
        text, _encoding = read(filepath)

    elapsed = time.perf_counter() - t0
    return text, elapsed
