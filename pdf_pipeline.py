"""PDF 解析管线：文字层为主，缺文字页回退 OCR + 表格识别。

策略（两档）：
  档 A  所有页原生文字充足 → 直接用 markitdown 整文档解析（保留现状质量）。
  档 B  存在缺文字页(低文字/扫描/图片主导) → 逐页拼接：
         - 文字页：pdfminer 抽文字层（不做 OCR / 图像表格识别）
         - 缺文字页：渲染为位图 → RapidOCR 正文，命中则叠加表格重建

渲染：生产用 poppler(pdftoppm) + pdf2image（避免 MuPDF License）。
开发环境缺 poppler 时回退 pypdfium2(BSD) 以便本地联调——Docker 有 poppler，走真路径。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

from config import SETTINGS
from markitdown import MarkItDown
import ocr as ocr_mod
import table_rec as table_mod

log = logging.getLogger("docparse.pdf")

_PAGE_BREAK = "\n\n---\n\n"
_OCR_BLOCK = "\n\n> OCR 识别内容（图片/扫描页，页码 {n}）：\n\n"

_md = MarkItDown()


# ---------------------------------------------------------------- 文字层提取
def _page_text_lengths(pdf_path: str | Path) -> list[int]:
    """返回每页原生文字长度。"""
    lengths = []
    for page in extract_pages(str(pdf_path)):
        n = sum(len(c.get_text()) for c in page if isinstance(c, LTTextContainer))
        lengths.append(n)
    return lengths


def _pdfminer_page_text(pdf_path: str | Path, page_index: int) -> str:
    """用 pdfminer 抽某页文字层。page_index 从 0 起。"""
    parts = []
    for i, page in enumerate(extract_pages(str(pdf_path))):
        if i != page_index:
            continue
        for c in page:
            if isinstance(c, LTTextContainer):
                parts.append(c.get_text())
        break
    return "".join(parts).strip()


# ---------------------------------------------------------------- 渲染
def _render_page(pdf_path: str | Path, page_index: int, dpi: int):
    """渲染指定页为 PIL.Image(模式 RGB)。优先 poppler；缺时回退 pypdfium2(dev)。"""
    try:
        from pdf2image import convert_from_path

        images = convert_from_path(
            str(pdf_path), dpi=dpi, first_page=page_index + 1, last_page=page_index + 1
        )
        if not images:
            raise RuntimeError(f"pdftoppm 未渲染出第 {page_index + 1} 页")
        return images[0].convert("RGB")
    except Exception as poppler_err:  # pragma: no cover
        if shutil.which("pdftoppm") is not None:
            raise
        # 缺 poppler(本地 dev)：回退 pypdfium2
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(pdf_path))
            try:
                page = doc[page_index]
                return page.render(scale=dpi / 72.0).to_pil().convert("RGB")
            finally:
                doc.close()
        except Exception:
            raise RuntimeError(
                "缺少 poppler(pdftoppm)。Docker 内已 apt 安装 poppler-utils；"
                f"本地可 brew/apt 安装或安装 pypdfium2。原错误: {poppler_err}"
            ) from poppler_err


# ---------------------------------------------------------------- 缺文字页 OCR 页
def _ocr_page_markdown(pdf_path: str | Path, page_index: int, dpi: int) -> str:
    """单页 OCR：一页只跑一次 RapidOCR；正文与表格共用结果。
    只有页面排布疑似含表格时才调用慢速表格模型，否则跳过。
    """
    img = _render_page(pdf_path, page_index, dpi)

    out = ocr_mod.ocr_output(img)  # 一次识别，正文 + 表格共用
    lines = ocr_mod.lines_from_output(out)
    md = ocr_mod.paragraphs(lines)

    if (
        lines
        and md
        and SETTINGS.table_enabled
        and table_mod.available()
        and ocr_mod.looks_like_table_layout(lines)
    ):
        try:
            html = table_mod.recover_table(img, out.boxes, out.txts, out.scores)
            if html:
                md_table = table_mod.html_to_markdown(html)
                if md_table:
                    md = f"{md}\n\n{md_table}".strip()
        except Exception as exc:  # pragma: no cover
            log.warning("表格识别异常(page %s): %s", page_index, exc)

    return md or "(该页未能识别到文本)"


def _needs_ocr(length: int) -> bool:
    return length < SETTINGS.pdf_text_min_chars


# ---------------------------------------------------------------- 主入口
def parse_pdf(pdf_path: str | Path) -> str:
    """返回 Markdown。外部应在文档确实是 PDF 时才调用。"""
    mode = SETTINGS.effective_mode()
    if mode == "never":
        # 强制不 OCR：退回 markitdown
        return _md.convert(str(pdf_path)).text_content

    lengths = _page_text_lengths(pdf_path)
    n_pages = len(lengths)
    low_pages = [i for i, n in enumerate(lengths) if _needs_ocr(n)]

    if mode == "auto" and not low_pages:
        # 档 A：全文字页，保留 markitdown 质量
        return _md.convert(str(pdf_path)).text_content

    # 档 B（auto 且存在缺文字页 / 或 always）：逐页拼接
    parts: list[str] = []
    for i in range(n_pages):
        if _needs_ocr(lengths[i]):
            parts.append(_OCR_BLOCK.format(n=i + 1) + _ocr_page_markdown(pdf_path, i, SETTINGS.dpi))
        else:
            text = _pdfminer_page_text(pdf_path, i)
            if text:
                parts.append(text)
    return _PAGE_BREAK.join(p for p in parts if p)


def needs_ocr_signal(pdf_path: str | Path) -> list[int]:
    """暴露哪些页被判定为缺文字（供测试/诊断）。"""
    return [i for i, n in enumerate(_page_text_lengths(pdf_path)) if _needs_ocr(n)]
