"""文本质量判定：识别"水印噪声"，用于决定某页是否真的缺文字（该不该 OCR）。

背景（真实案例）：
  部分招聘网站导出的 PDF，页面可见内容其实是**图片**，但文字层里残留了水印——
  一个长 token（如 `176ee020…~~`）+ 一列竖排单字符（`f`/`~`/`w`/`3`…）。
  若直接按字符数判断，水印会把该页撑到阈值以上，被误判成"有文字页"→ 跳过 OCR →
  最终解析出**空内容或纯噪声**。

解决：
  meaningful_length() 先剔除水印类噪声，再统计剩余**有效字符数**，用它来做
  "该页是否缺文字"的判断。语言无关：正常中/英文正文的词都是多字符、成句的，
  不会被误删；只有"长随机 token""孤立单字符连排""纯符号行"这类才被当作噪声。

保守原则：宁可少删，不可误删——只处理特征非常明确的噪声形态。
"""
from __future__ import annotations

import re

# 长随机 token：>=16 个字母数字/下划线/连字符，可带尾部符号（水印特征）
_TOKEN_RE = re.compile(r"^[0-9A-Za-z_\-]{16,}[~^=+\-_.]{0,6}$")
# 纯符号行（分隔线、装饰符）
_SYMBOL_RE = re.compile(r"^[~^=+\-*|_.·…:：,，、;；/\\ ]{1,8}$")


def _is_lone_char(line: str) -> bool:
    """孤立的单个 ASCII 字符（水印竖排字的形态）。"""
    return len(line) == 1 and line.isascii()


def strip_noise(text: str) -> list[str]:
    """去掉水印类噪声行，返回保留下来的行。"""
    kept: list[str] = []
    for raw in text.split("\n"):
        s = raw.strip()
        if not s:
            continue
        if _TOKEN_RE.fullmatch(s):        # 长随机 token
            continue
        if _SYMBOL_RE.fullmatch(s):       # 纯符号行
            continue
        kept.append(s)

    # 连续 >=3 个"孤立单字符"行 → 判为竖排水印，整段删除
    out: list[str] = []
    i = 0
    n = len(kept)
    while i < n:
        if _is_lone_char(kept[i]):
            j = i
            while j < n and _is_lone_char(kept[j]):
                j += 1
            if j - i >= 3:
                i = j                      # 丢弃该连续段
                continue
        out.append(kept[i])
        i += 1
    return out


def meaningful_length(text: str) -> int:
    """剔除水印噪声后的有效字符数（不计空白）。"""
    return sum(len("".join(line.split())) for line in strip_noise(text))
