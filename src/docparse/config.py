"""全局配置：OCR / 表格识别 / PDF 管线参数。

所有项都可用同名环境变量覆盖（大写）：
  OCR_MODE, PDF_TEXT_MIN_CHARS, OCR_DPI, TABLE_ENABLED, OCR_MODEL_DIR,
  OCR_INTRA_THREADS, OCR_INTER_THREADS
OCR 是默认能力、无需开关；要关闭用 OCR_MODE=never。
PDF 不走 markitdown；渲染统一用 pypdfium2（无 poppler 依赖）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


@dataclass
class Settings:
    # OCR 模式：auto(有缺文字页才 OCR) / always / never(关闭)
    ocr_mode: str = "auto"
    # 页原生文字低于该值判为“缺文字页”→ OCR
    pdf_text_min_chars: int = 300
    # 渲染分辨率（pypdfium2 光栅化用）
    dpi: int = 200
    # 无文字层页是否尝试表格重建（慢；默认关闭，需结构时用 TABLE_ENABLED=true 开启）
    table_enabled: bool = False
    # ONNX 模型根目录；None = 用各包默认（dev 自动下载）
    model_dir: str | None = None
    # onnxruntime intra-op 线程数（<=0 = 自动）。
    # 实测「自动」会按可见核数开满线程池，容器里超额订阅反而最慢：
    #   Mac 12 核 auto=0.936s/页 vs 6 线程=0.468s；服务器 96 核 auto=1.676s vs 16 线程=0.766s
    # 注意 OMP_NUM_THREADS 对本环境 onnxruntime 无效，必须用本项。
    ocr_intra_threads: int = 0
    # onnxruntime inter-op 线程数（<=0 = 自动）
    ocr_inter_threads: int = 0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ocr_mode=os.environ.get("OCR_MODE", "auto").strip().lower(),
            pdf_text_min_chars=_int_env("PDF_TEXT_MIN_CHARS", 300),
            dpi=_int_env("OCR_DPI", 200),
            table_enabled=_bool_env("TABLE_ENABLED", False),
            model_dir=os.environ.get("OCR_MODEL_DIR") or None,
            ocr_intra_threads=_int_env("OCR_INTRA_THREADS", 0),
            ocr_inter_threads=_int_env("OCR_INTER_THREADS", 0),
        )

    def effective_mode(self) -> str:
        mode = self.ocr_mode
        if mode not in {"auto", "always", "never"}:
            return "auto"
        return mode


SETTINGS = Settings.from_env()


def dump() -> dict[str, object]:
    return {f.name: getattr(SETTINGS, f.name) for f in fields(SETTINGS)}
