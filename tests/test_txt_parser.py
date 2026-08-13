import pytest

from txt_parser import parse


def test_parse_utf8(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("你好世界".encode("utf-8"))
    text, enc = parse(p)
    assert text == "你好世界"
    assert enc == "utf-8"


def test_parse_gb18030(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("中文内容".encode("gb18030"))
    text, enc = parse(p)
    assert text == "中文内容"
    assert enc == "gb18030"


def test_parse_explicit_encoding(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("中文".encode("gbk"))
    text, enc = parse(p, encoding="gbk")
    assert text == "中文"
    assert enc == "gbk"


def test_parse_fallback_latin1(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"\xff")
    text, enc = parse(p)
    assert enc == "latin-1"
    assert text == "\xff"
