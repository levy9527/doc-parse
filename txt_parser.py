from pathlib import Path


ENCODINGS = [
    "utf-8",
    "utf-16",
    "gb18030",
    "gbk",
    "big5",
    "shift_jis",
    "euc-jp",
    "euc-kr",
    "latin-1",
]


def read_txt(filepath: str | Path, encoding: str | None = None) -> tuple[str, str]:
    filepath = Path(filepath)
    with open(filepath, "rb") as f:
        raw = f.read()

    if encoding:
        return raw.decode(encoding), encoding

    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue

    raise ValueError(f"无法识别文件编码: {filepath}")
