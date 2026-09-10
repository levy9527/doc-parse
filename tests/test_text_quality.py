"""text_quality 测试：水印噪声剔除 + 有效长度判定。"""
from text_quality import meaningful_length, strip_noise

# 真实模板水印：长 token + 竖排单字符 + 符号分隔
_WATERMARK = """176ee020586f3dd11Hx53NW4EVtWxI6_UPuaWOGjmfXZMxhn3w~~
f
~
~
w
3
n
h
x
M
Z
X
m
G
O
W
a
u
P
U
_
6
j
176ee020586f3dd11Hx53NW4EVtWxI6_UPuaWOGjmfXZMxhn3w~~

---
"""

_NORMAL = """郑露
电话：13636737358 邮箱：2541400641@qq.com 最高学历：本科
自我评价：熟悉 React、Vue 框架，掌握 TypeScript 与 Node.js 服务端开发。
工作经历 2024.03-至今 陕西久安源建筑装饰工程有限公司 FDE 前沿部署工程师
"""


def test_watermark_text_has_near_zero_meaningful_length():
    assert meaningful_length(_WATERMARK) < 50


def test_normal_text_is_not_stripped():
    # 正常正文的有效长度应与去空白后的字符数接近（不误删）
    compact = len("".join(_NORMAL.split()))
    assert meaningful_length(_NORMAL) == compact


def test_strip_noise_removes_tokens_and_vertical_column():
    kept = strip_noise(_WATERMARK)
    assert kept == []  # 只剩水印 → 全被剔除


def test_isolated_single_char_is_kept():
    # 单个孤立字符（非连续段）不算水印，保留
    text = "Java\nC\nPython 后端开发工程师"
    assert meaningful_length(text) > 0
    assert "C" in strip_noise(text)


def test_long_word_not_treated_as_token():
    # 长英文单词（<16）不应被误删
    text = "communicate effectively with stakeholders"
    assert meaningful_length(text) == len("".join(text.split()))


def test_watermark_dominated_page_is_detected():
    """判定规则：原文够长但几乎全是水印 → 应判为缺文字（走 OCR）。"""
    import pdf_pipeline

    # 郑露这类：原文 422 字，去掉水印后几乎没有有效文字
    assert pdf_pipeline._page_needs_ocr(422, 8) is True


def test_normal_page_is_not_flagged_as_low_text():
    """正常正文页：去噪损失很小 → 不应改变原有判定（仍视为有文字页）。"""
    import pdf_pipeline

    # demo.pdf 第 5 页这类：原文 338，去噪后仍 285（噪声仅 ~16%）
    assert pdf_pipeline._page_needs_ocr(338, 285) is False


def test_short_page_still_uses_original_rule():
    import pdf_pipeline

    # 原有规则保持不变：原文就低于阈值 → OCR
    assert pdf_pipeline._page_needs_ocr(250, 240) is True
