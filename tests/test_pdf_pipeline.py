"""PDF 管线测试：用仓库内 demo.pdf（全文字页 → 档A）验证判定与解析不回归。

重引擎(OCR/表格)相关不在此测试，保持套件轻量。
"""
from pathlib import Path

from markitdown import MarkItDown

import docparse.pdf_pipeline as pdf_pipeline
from docparse.config import SETTINGS

DEMO = Path(__file__).resolve().parent.parent / "demo" / "demo.pdf"


def test_demo_is_text_pdf():
    # demo.pdf 每页都有充足文字 → 判定无缺文字页
    assert DEMO.exists()
    assert pdf_pipeline.needs_ocr_signal(DEMO) == []


def test_parse_pdf_tier_a_matches_markitdown():
    # 无缺文字页 → 档A，走 markitdown 整文档
    out = pdf_pipeline.parse_pdf(DEMO)
    assert out and len(out) > 100
    md = MarkItDown().convert(str(DEMO)).text_content
    assert out == md


def test_needs_ocr_threshold():
    assert pdf_pipeline._needs_ocr(SETTINGS.pdf_text_min_chars - 1) is True
    assert pdf_pipeline._needs_ocr(SETTINGS.pdf_text_min_chars + 1) is False
