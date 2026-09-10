"""PDF 管线测试：验证「PDF 不走 markitdown」、缺文字判定、模式语义与渲染。

用仓库内 demo.pdf（全文字页）。重引擎(OCR)不在此触发，保持套件轻量。
"""
from pathlib import Path

from markitdown import MarkItDown

import docparse.pdf_pipeline as pdf_pipeline
from docparse.config import SETTINGS

DEMO = Path(__file__).resolve().parent.parent / "demo" / "demo.pdf"


def test_demo_is_text_pdf():
    # demo.pdf 每页都有充足文字 → 无缺文字页
    assert DEMO.exists()
    assert pdf_pipeline.needs_ocr_signal(DEMO) == []


def test_parse_pdf_does_not_use_markitdown():
    # PDF 一律逐页处理，不再走 markitdown
    out = pdf_pipeline.parse_pdf(DEMO)
    assert out and len(out) > 100
    assert "OCR 识别内容" not in out
    md = MarkItDown().convert(str(DEMO)).text_content
    assert out != md, "PDF 不应再走 markitdown"


def test_parse_pdf_comes_from_pdfminer_text_layer():
    out = pdf_pipeline.parse_pdf(DEMO)
    page0 = pdf_pipeline._pdfminer_page_text(DEMO, 0)
    assert page0, "demo.pdf 第 1 页应有文字层"
    assert page0.strip() in out


def test_needs_ocr_threshold():
    assert pdf_pipeline._needs_ocr(SETTINGS.pdf_text_min_chars - 1) is True
    assert pdf_pipeline._needs_ocr(SETTINGS.pdf_text_min_chars + 1) is False


def test_watermark_dominated_page_is_detected():
    # 郑露这类：原文 422 字但去水印后几乎没有有效文字
    assert pdf_pipeline._page_needs_ocr(422, 8) is True


def test_normal_page_is_not_flagged_as_low_text():
    # demo.pdf 第 5 页这类：噪声占比很小 → 不改变判定
    assert pdf_pipeline._page_needs_ocr(338, 285) is False


def test_short_page_still_uses_original_rule():
    assert pdf_pipeline._page_needs_ocr(250, 240) is True


def test_mode_semantics():
    # always: 每页都 OCR；never: 一律不 OCR；auto: 仅缺文字页 OCR
    assert pdf_pipeline._should_ocr_page("always", 1000, 900) is True
    assert pdf_pipeline._should_ocr_page("never", 10, 0) is False
    assert pdf_pipeline._should_ocr_page("auto", 10, 0) is True
    assert pdf_pipeline._should_ocr_page("auto", 1000, 900) is False


def test_render_page_uses_pdfium_and_returns_rgb():
    from PIL import Image

    img = pdf_pipeline._render_page(DEMO, 0, 100)
    assert isinstance(img, Image.Image)
    assert img.mode == "RGB"
    assert img.size[0] > 100 and img.size[1] > 100
