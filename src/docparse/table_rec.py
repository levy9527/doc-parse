"""表格结构识别：table_cls(有线/无线) + wired_table_rec / lineless_table_rec。

输入一张“无文字层”页面的位图 + 同一页面 RapidOCR 的结果（boxes/txts/scores），
输出结构化 Markdown 表格；若实际没检出真实表格，返回 None（由调用方回退到纯 OCR 文本）。
"""
from __future__ import annotations

import logging
from html.parser import HTMLParser
from typing import Optional

log = logging.getLogger("docparse.table")

try:  # pragma: no cover
    from table_cls import TableCls
    from wired_table_rec.main import WiredTableInput, WiredTableRecognition
    from lineless_table_rec.main import LinelessTableInput, LinelessTableRecognition
except Exception as exc:  # pragma: no cover
    TableCls = WiredTableRecognition = LinelessTableRecognition = None
    _IMPORT_ERR = exc
else:  # pragma: no cover
    _IMPORT_ERR = None

_tbl_cls: Optional["TableCls"] = None
_wired = None
_lineless = None


def available() -> bool:
    return TableCls is not None and WiredTableRecognition is not None


def _cls_engine():
    global _tbl_cls
    if _tbl_cls is None:
        if TableCls is None:  # pragma: no cover
            raise RuntimeError(f"表格识别依赖不可用: {_IMPORT_ERR}")
        log.info("初始化 table_cls...")
        _tbl_cls = TableCls()
    return _tbl_cls


def _wired_engine():
    global _wired
    if _wired is None:
        log.info("初始化 wired_table_rec...")
        _wired = WiredTableRecognition(WiredTableInput())
    return _wired


def _lineless_engine():
    global _lineless
    if _lineless is None:
        log.info("初始化 lineless_table_rec...")
        _lineless = LinelessTableRecognition(LinelessTableInput())
    return _lineless


def classify_table(img) -> str:
    """返回 'wired' 或 'wireless'。仅加载 table_cls。"""
    cls, _ = _cls_engine()(img)
    return cls


def recover_table(img, boxes, txts, scores) -> Optional[str]:
    """用 OCR 结果重建表格，返回 pred_html；失败/无表返回 None。

    boxes/txts/scores 来自同一次 rapidocr 识别，保证单元格与正文共用，不重复识别。
    按分类结果只加载需要的分支引擎（wired 或 lineless 之一）。
    """
    cls = classify_table(img)
    if cls == "wired":
        engine = _wired_engine()
    else:
        engine = _lineless_engine()
    img = _to_engine_input(img)
    ocr_result = []
    try:
        import numpy as np

        for b, t, s in zip(boxes, txts, scores):
            a = np.asarray(b, dtype=float).reshape(-1, 2)
            ocr_result.append([a.tolist(), str(t), float(s)])
    except Exception as exc:  # pragma: no cover
        log.warning("OCR 结果转换失败: %s", exc)
        return None
    try:
        result = engine(img, ocr_result=ocr_result)
    except Exception as exc:  # pragma: no cover
        log.warning("表格识别失败: %s", exc)
        return None
    html = (getattr(result, "pred_html", None) or "").strip()
    if not html or not _looks_like_real_table(html):
        return None
    return html


def _to_engine_input(img):
    """wired/lineless 只收 str/ndarray/bytes/Path；把 PIL.Image 转成 ndarray。"""
    try:
        from PIL import Image
    except Exception:  # pragma: no cover
        return img
    if isinstance(img, Image.Image):
        import numpy as np

        return np.asarray(img)
    return img


def _looks_like_real_table(html: str) -> bool:
    """验收门控：pred_html 是否真的是多行/多列的表格，而非整页文本被包成单格。"""
    rows = html.lower().split("<tr")
    cells = html.lower().split("<td")
    return len(rows) >= 3 and len(cells) >= 3


class _TableParser(HTMLParser):
    """把 <table> 转成二维单元格字符串（best-effort，忽略合并行/列跨度细节）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "tr":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = []
        elif t == "td" or t == "th":
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "td" or t == "th":
            if self._row is not None and self._cell is not None:
                self._row.append("".join(self._cell).strip())
            self._cell = None
        elif t == "tr":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = None
        elif t == "table":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = None

    def table(self) -> list[list[str]]:
        if self._row is not None:
            self.rows.append(self._row)
        self._row = None
        # 补齐行宽
        if not self.rows:
            return []
        width = max(len(r) for r in self.rows)
        return [r + [""] * (width - len(r)) for r in self.rows if r]


def html_to_markdown(html: str) -> Optional[str]:
    """把表格 HTML 转成 GitHub 风格管道表格。"""
    p = _TableParser()
    try:
        p.feed(html)
    except Exception:  # pragma: no cover
        return None
    table = p.table()
    if not table:
        return None
    width = len(table[0])
    if width == 0:
        return None
    rows = [[c.replace("\n", " ").replace("|", "\\|").strip() for c in row] for row in table]
    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
