"""OCR/表格/PDF 管线相关配置与纯逻辑测试。"""
import importlib

import pytest

import docparse.config as config


def test_settings_defaults():
    s = config.Settings()
    assert s.pdf_text_min_chars == 300
    assert s.ocr_mode == "auto"
    assert s.dpi == 200
    assert s.table_enabled is False
    assert s.ocr_intra_threads == 8  # 默认 8：避免 onnxruntime auto 的超额订阅


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("OCR_MODE", "always")
    monkeypatch.setenv("PDF_TEXT_MIN_CHARS", "500")
    monkeypatch.setenv("OCR_DPI", "300")
    monkeypatch.setenv("TABLE_ENABLED", "0")
    monkeypatch.setenv("OCR_INTRA_THREADS", "16")
    s = config.Settings.from_env()
    assert s.ocr_mode == "always"
    assert s.pdf_text_min_chars == 500
    assert s.dpi == 300
    assert s.table_enabled is False
    assert s.ocr_intra_threads == 16


def test_effective_mode():
    # OCR 默认开启(auto)；never 才关闭；非法值回退 auto
    assert config.Settings().effective_mode() == "auto"
    assert config.Settings(ocr_mode="always").effective_mode() == "always"
    assert config.Settings(ocr_mode="never").effective_mode() == "never"
    assert config.Settings(ocr_mode="bogus").effective_mode() == "auto"
