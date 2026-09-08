"""全局配置：OCR / 表格识别 / PDF 管线参数。

所有项都可用同名环境变量覆盖（大写）：
  OCR_ENABLED, OCR_MODE, PDF_TEXT_MIN_CHARS, OCR_DPI,
  TABLE_ENABLED, OCR_MODEL_DIR
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields


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
    # 是否启用 OCR 回退
    ocr_enabled: bool = True
    # auto(有缺文字页才 OCR) / always / never
    ocr_mode: str = "auto"
    # 页原生文字低于该值判为“缺文字页”→ OCR
    pdf_text_min_chars: int = 300
    # 渲染分辨率（poppler pdftoppm / pdf2image 用）
    dpi: int = 200
    # 无文字层页是否尝试表格重建（慢；默认关闭，需结构时用 TABLE_ENABLED=true 开启）
    table_enabled: bool = False
    # ONNX 模型根目录；None = 用各包默认（dev 自动下载）
    model_dir: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ocr_enabled=_bool_env("OCR_ENABLED", True),
            ocr_mode=os.environ.get("OCR_MODE", "auto").strip().lower(),
            pdf_text_min_chars=_int_env("PDF_TEXT_MIN_CHARS", 300),
            dpi=_int_env("OCR_DPI", 200),
            table_enabled=_bool_env("TABLE_ENABLED", False),
            model_dir=os.environ.get("OCR_MODEL_DIR") or None,
        )

    def effective_mode(self) -> str:
        if not self.ocr_enabled:
            return "never"
        mode = self.ocr_mode
        if mode not in {"auto", "always", "never"}:
            return "auto"
        return mode


SETTINGS = Settings.from_env()


def dump() -> dict[str, object]:
    return {f.name: getattr(SETTINGS, f.name) for f in fields(SETTINGS)}
