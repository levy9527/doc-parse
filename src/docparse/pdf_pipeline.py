"""PDF 解析管线：文字层为主，缺文字页回退 OCR + 表格识别。

策略：**PDF 不再使用 markitdown**。markitdown 会把招聘模板简历的水印竖列/分栏
误判成 markdown 表格，导致「结构被伪造 + 水印字符与正文粘连」（实测技能词
`Webpack` 被写成 `Webpackd`，词边界匹配失配）。改为逐页处理：
    - 文字页  ：pdfminer 抽文字层（不做 OCR / 图像表格识别）
    - 缺文字页：渲染为位图 → RapidOCR 正文，命中则叠加表格重建

OCR 模式（`OCR_MODE`）：
    auto   默认，只对「缺文字页」OCR
    always 每页都强制 OCR（忽略文字层；慢，用于排查/质检）
    never  完全不 OCR（缺文字页留占位提示）

渲染：pypdfium2（PDFium, BSD）**进程内**渲染——无子进程、无临时文件。
（原 poppler(pdftoppm)+pdf2image 逐页 fork 子进程 + 临时文件往返，实测比 PDFium
 慢约 4.8 倍，已整体移除。）
"""
from __future__ import annotations

import logging
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

from docparse.config import SETTINGS
from docparse import ocr as ocr_mod
from docparse import table_rec as table_mod
from docparse.text_quality import meaningful_length

log = logging.getLogger("docparse.pdf")

_PAGE_BREAK = "\n\n---\n\n"
_OCR_BLOCK = "\n\n> OCR 识别内容（图片/扫描页，页码 {n}）：\n\n"
_NO_TEXT_BLOCK = "\n\n> 该页无文字层，且已关闭 OCR（页码 {n}）：\n\n"

# 判为「水印主导页」的噪声占比阈值：原文够长，但去掉噪声后所剩无几
_WATERMARK_NOISE_RATIO = 0.5


# ---------------------------------------------------------------- 文字层统计
def _page_stats(pdf_path: str | Path) -> list[tuple[int, int]]:
    """返回每页 (原始字符数, 去噪后有效字符数)。

    招聘模板 PDF 的可见内容是图片，文字层却残留水印（长 token + 竖排单字符）。
    原始字符数会被水印撑到阈值以上 → 误判「有文字页」→ 跳过 OCR → 解析出空内容。
    因此除原始长度外，另算一个去水印后的有效长度，供判定使用。
    """
    stats: list[tuple[int, int]] = []
    for page in extract_pages(str(pdf_path)):
        text = "".join(
            c.get_text() for c in page if isinstance(c, LTTextContainer)
        )
        stats.append((len(text), meaningful_length(text)))
    return stats


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
    """渲染指定页为 PIL.Image(模式 RGB)：pypdfium2(PDFium) 进程内渲染。

    无子进程、无临时文件；不再使用 poppler。
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        return page.render(scale=dpi / 72.0).to_pil().convert("RGB")
    finally:
        doc.close()


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


def _page_needs_ocr(raw_len: int, meaningful_len: int) -> bool:
    """该页是否应按「缺文字页」处理（→ OCR）。

    两条判据，取"或"，**只增不减**（不会让原本会 OCR 的页变成不 OCR）：
      1) 原有规则：原始字符数 < 阈值。
      2) 新增：水印主导页——原始字符数够长，但去掉水印噪声后有效文字不足阈值，
         且噪声占比超过 _WATERMARK_NOISE_RATIO。
    第 2 条专门救「可见内容是图片、文字层只剩水印」的模板 PDF；对正常正文页，
    去噪损失极小（噪声占比远低于阈值），判定结果与原来一致。
    """
    if _needs_ocr(raw_len):
        return True
    noise = raw_len - meaningful_len
    if meaningful_len < SETTINGS.pdf_text_min_chars and noise >= raw_len * _WATERMARK_NOISE_RATIO:
        return True
    return False


def _should_ocr_page(mode: str, raw_len: int, meaningful_len: int) -> bool:
    """本页是否走 OCR。三种模式语义：
    always → 每页都 OCR；never → 一律不 OCR；auto → 仅「缺文字页」OCR。
    """
    if mode == "always":
        return True
    if mode == "never":
        return False
    return _page_needs_ocr(raw_len, meaningful_len)


# ---------------------------------------------------------------- 主入口
def parse_pdf(pdf_path: str | Path) -> str:
    """返回 Markdown。外部应在文档确实是 PDF 时才调用。

    注意：PDF **不走 markitdown**，一律逐页处理（文字页 pdfminer / 缺文字页 OCR）。
    """
    mode = SETTINGS.effective_mode()
    stats = _page_stats(pdf_path)
    parts: list[str] = []
    for i, (raw_len, meaningful_len) in enumerate(stats):
        if _should_ocr_page(mode, raw_len, meaningful_len):
            parts.append(
                _OCR_BLOCK.format(n=i + 1)
                + _ocr_page_markdown(pdf_path, i, SETTINGS.dpi)
            )
        else:
            text = _pdfminer_page_text(pdf_path, i)
            if text:
                parts.append(text)
            elif mode == "never":
                parts.append(_NO_TEXT_BLOCK.format(n=i + 1))
    return _PAGE_BREAK.join(p for p in parts if p)


def needs_ocr_signal(pdf_path: str | Path) -> list[int]:
    """暴露哪些页被判定为缺文字（供测试/诊断）。"""
    return [i for i, (raw, ml) in enumerate(_page_stats(pdf_path)) if _page_needs_ocr(raw, ml)]
