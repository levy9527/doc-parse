from doc_parser import MARKITDOWN_EXTENSIONS, parse


def test_parse_html(tmp_path):
    p = tmp_path / "a.html"
    p.write_text("<h1>标题</h1><p>正文内容</p>", encoding="utf-8")
    text = parse(p)
    assert text.strip()
    assert "正文内容" in text


def test_parse_txt_fallback(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("纯文本", encoding="utf-8")
    text = parse(p)
    assert text == "纯文本"


def test_markitdown_extensions():
    assert ".pdf" in MARKITDOWN_EXTENSIONS
    assert ".docx" in MARKITDOWN_EXTENSIONS
    assert ".txt" not in MARKITDOWN_EXTENSIONS
