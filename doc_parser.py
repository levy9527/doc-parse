from pathlib import Path

from markitdown import MarkItDown

from txt_parser import parse as parse_txt

MARKITDOWN_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".html", ".htm", ".csv", ".json", ".xml",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
    ".epub", ".zip",
}

_md = MarkItDown()


def parse(filepath: str | Path) -> str:
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext in MARKITDOWN_EXTENSIONS:
        result = _md.convert(str(filepath))
        return result.text_content

    return parse_txt(filepath)[0]
