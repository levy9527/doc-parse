from pathlib import Path


ENCODINGS = ["utf-8", "gbk", "gb2312", "gb18030", "latin-1"]


def _detect(raw: bytes) -> str:
    for enc in ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def read_txt(filepath: str | Path, encoding: str | None = None) -> tuple[str, str]:
    filepath = Path(filepath)
    with open(filepath, "rb") as f:
        raw = f.read()
    enc = encoding or _detect(raw)
    return raw.decode(enc), enc
