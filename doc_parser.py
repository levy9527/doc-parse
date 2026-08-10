from pathlib import Path

from markitdown import MarkItDown

from txt_parser import parse as parse_txt

MARKITDOWN_EXTENSIONS = {
    ".docx",
    ".csv",
    ".xls",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".htm",
    ".html",
    ".epub",
    ".ipynb",
    ".jpg",
    ".jpeg",
    ".json",
    ".jsonl",
    ".m4a",
    ".mp3",
    ".mp4",
    ".msg",
    ".png",
    ".rss",
    ".atom",
    ".wav",
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


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="解析文档为 Markdown")
    p.add_argument("filepath", help="输入文件路径")
    p.add_argument("-o", "--output", help="输出文件路径（默认输出到 stdout）")
    args = p.parse_args()

    text = parse(args.filepath)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"已保存: {args.output}", file=sys.stderr)
    else:
        print(text)
