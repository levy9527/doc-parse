"""RapidOCR(ONNX) 行级 OCR 封装。

- 懒加载单例：首次调用才初始化引擎（会加载 ONNX 模型）。
- ocr_lines(img) / ocr_output(img)：识别图片，返回排序后的识别行 / 原始结构化输出。
- 关键优化：一页只跑一次引擎，正文文本与（可选的）表格重建共用同一次识别结果。
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger("docparse.ocr")

try:  # pragma: no cover - 依赖导入
    from rapidocr import RapidOCR
except Exception as exc:  # pragma: no cover
    RapidOCR = None
    _IMPORT_ERR = exc
else:  # pragma: no cover
    _IMPORT_ERR = None

_engine: "RapidOCR | None" = None


@dataclass
class OCRLine:
    text: str
    score: float
    box: list  # 4x2 [[x1,y1],...]
    # 简化 bbox（用于阅读序排序 / 布局几何判断）
    top: float
    left: float
    right: float
    bottom: float

    @classmethod
    def from_raw(cls, box, text, score) -> "OCRLine":
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        return cls(
            text=str(text),
            score=float(score),
            box=box,
            top=float(min(ys)),
            left=float(min(xs)),
            right=float(max(xs)),
            bottom=float(max(ys)),
        )


def available() -> bool:
    return RapidOCR is not None


def engine_params() -> dict | None:
    """按配置生成 RapidOCR 引擎参数。

    线程数很关键：onnxruntime 默认(auto)会按可见核数开线程池，实测在容器里
    **超额订阅反而最慢**（Mac 12 核：auto 0.936s/页 → intra_op=6 时 0.468s；
    服务器 96 核：auto 1.676s/页 → intra_op=16 时 0.766s，约 2 倍）。
    注意 `OMP_NUM_THREADS` 对本环境的 onnxruntime **无效**，必须设这个参数。
    """
    from docparse.config import SETTINGS

    params: dict = {}
    if SETTINGS.ocr_intra_threads > 0:
        params["EngineConfig.onnxruntime.intra_op_num_threads"] = SETTINGS.ocr_intra_threads
    if SETTINGS.ocr_inter_threads > 0:
        params["EngineConfig.onnxruntime.inter_op_num_threads"] = SETTINGS.ocr_inter_threads
    return params or None


def get_engine():
    """懒加载 RapidOCR 单例。"""
    global _engine
    if _engine is not None:
        return _engine
    if RapidOCR is None:  # pragma: no cover
        raise RuntimeError(f"rapidocr 不可用: {_IMPORT_ERR}")
    params = engine_params()
    log.info("初始化 RapidOCR 引擎... (params=%s)", params)
    _engine = RapidOCR(params=params) if params else RapidOCR()
    return _engine


def ocr_output(img):
    """识别一次并返回原始结构化输出（含 boxes/txts/scores），供正文与表格共用。"""
    return get_engine()(img)


def lines_from_output(out) -> list["OCRLine"]:
    if out is None or not getattr(out, "txts", None):
        return []
    lines = [
        OCRLine.from_raw(b, t, s)
        for b, t, s in zip(out.boxes, out.txts, out.scores)
    ]
    return _sort_lines(lines)


def _sort_lines(lines: list["OCRLine"]) -> list["OCRLine"]:
    """按阅读序排序：先按行(y 中心)分桶，桶内按 x。"""
    if not lines:
        return lines
    rows = _group_rows(lines)
    ordered: list[OCRLine] = []
    for row in rows:
        for line in sorted(row, key=lambda l: l.left):
            ordered.append(line)
    return ordered


def _group_rows(lines: list["OCRLine"]) -> list[list["OCRLine"]]:
    """把文字行按垂直中心聚成“文本行”，用于阅读序与列对齐判断。"""
    rows: list[list[OCRLine]] = []
    for line in sorted(lines, key=lambda l: (l.top + l.bottom) / 2.0):
        cy = (line.top + line.bottom) / 2.0
        for row in rows:
            if abs(cy - (row[0].top + row[0].bottom) / 2.0) <= max(
                0.6 * (row[0].bottom - row[0].top), 8.0
            ):
                row.append(line)
                break
        else:
            rows.append([line])
    return sorted(rows, key=lambda r: (r[0].top + r[0].bottom) / 2.0)


def _lines_to_paragraphs(lines: list["OCRLine"]) -> list[str]:
    """按行间距把识别行聚合成段落。"""
    if not lines:
        return []
    med_h = 1
    heights = sorted((l.bottom - l.top) for l in lines)
    if heights:
        med_h = heights[len(heights) // 2] or 1.0
    paras: list[str] = []
    cur: list[str] = []
    prev_bottom: float | None = None
    for line in lines:
        gap = 0.0
        if prev_bottom is not None:
            gap = line.top - prev_bottom
        if cur and (prev_bottom is not None) and gap > 1.8 * med_h:
            paras.append(" ".join(cur))
            cur = []
        cur.append(line.text.strip())
        prev_bottom = max(prev_bottom or 0.0, line.bottom)
    if cur:
        paras.append(" ".join(cur))
    return paras


def ocr_lines(img) -> list["OCRLine"]:
    """识别图片并返回排序后的识别行。"""
    return lines_from_output(ocr_output(img))


def paragraphs(lines: list["OCRLine"]) -> str:
    """把识别行聚合成段落 Markdown。lines 可为空。"""
    paras = _lines_to_paragraphs(lines)
    return "\n\n".join(p for p in paras if p)


def looks_like_table_layout(lines: list["OCRLine"]):
    """廉价几何判断：页面是否呈“数据网格 / 表格”排布。

    是才值得跑慢速有线/无线表格模型；封面、章节分隔、议程、纯散文页通常返回 False。
    依据：
      - 真数据网格：≥3 行，每行内出现 ≥3 个水平分离且不重叠的列块；或
      - 双列明细表：≥5 行出现 ≥2 列（如缩略词/名值对表）。
    """
    if len(lines) < 4:
        return False
    rows = _group_rows(lines)
    rows_ge2 = 0
    rows_ge3 = 0
    for row in rows:
        row = sorted(row, key=lambda l: l.left)
        cols = []
        for line in row:
            if cols and line.left < cols[-1][1] - 2.0:
                cols[-1][1] = max(cols[-1][1], line.right)
            else:
                cols.append([line.left, line.right])
        n = len(cols)
        if n >= 2:
            rows_ge2 += 1
        if n >= 3:
            rows_ge3 += 1
    return rows_ge3 >= 3 or rows_ge2 >= 5


def ocr_image_text(img) -> str:
    """识别图片并返回 Markdown 化文本（图片/独立文件入口用）。"""
    return paragraphs(ocr_lines(img))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    path = sys.argv[1]
    print(ocr_image_text(path))
