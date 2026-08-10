from pathlib import Path

from markitdown import MarkItDown

from txt_parser import parse as parse_txt

MARKITDOWN_EXTENSIONS = {
    ".csv",
    ".docx",
    ".epub",
    ".htm",
    ".html",
    ".ipynb",
    ".jpg",
    ".jpeg",
    ".json",
    ".jsonl",
    ".m4a",
    ".mp3",
    ".mp4",
    ".msg",
    ".pdf",
    ".png",
    ".pptx",
    ".rss",
    ".atom",
    ".wav",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}

_md = MarkItDown()


def parse(filepath: str | Path) -> str:
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext in MARKITDOWN_EXTENSIONS:
        result = _md.convert(str(filepath))
        return result.text_content

    return parse_txt(filepath)[0]
