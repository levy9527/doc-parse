"""OCR/表格/PDF 管线相关配置与纯逻辑测试。"""
import importlib

import pytest

import config


def test_settings_defaults():
    s = config.Settings()
    assert s.pdf_text_min_chars == 300
    assert s.ocr_mode == "auto"
    assert s.dpi == 200
    assert s.table_enabled is False  # 默认关闭，经 TABLE_ENABLED 开启


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("OCR_MODE", "always")
    monkeypatch.setenv("PDF_TEXT_MIN_CHARS", "500")
    monkeypatch.setenv("OCR_DPI", "300")
    monkeypatch.setenv("TABLE_ENABLED", "0")
    s = config.Settings.from_env()
    assert s.ocr_mode == "always"
    assert s.pdf_text_min_chars == 500
    assert s.dpi == 300
    assert s.table_enabled is False


def test_effective_mode():
    s = config.Settings(ocr_enabled=False, ocr_mode="always")
    assert s.effective_mode() == "never"  # 总开关优先
    s2 = config.Settings(ocr_enabled=True, ocr_mode="bogus")
    assert s2.effective_mode() == "auto"  # 非法回退 auto
    assert config.Settings(ocr_mode="always").effective_mode() == "always"
