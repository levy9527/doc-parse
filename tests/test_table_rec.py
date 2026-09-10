"""表格 HTML→Markdown 与结构门控的纯逻辑测试。"""
import pytest

import docparse.table_rec as table_rec

HTML_3x2 = """
<html><body><table>
<tr><td>a</td><td>b</td></tr>
<tr><td>1</td><td>2</td></tr>
<tr><td>x</td><td>y</td></tr>
</table></body></html>
"""


def test_looks_like_real_table():
    assert table_rec._looks_like_real_table(HTML_3x2) is True
    # 整页被包成单格/仅 1 行 → 不是真表
    assert table_rec._looks_like_real_table("<table><tr><td>整段正文很长很长</td></tr></table>") is False


def test_html_to_markdown():
    md = table_rec.html_to_markdown(HTML_3x2)
    assert md is not None
    lines = md.splitlines()
    assert lines[0].startswith("| a | b |")
    assert "---" in lines[1]
    assert "| 1 | 2 |" in lines[2]


def test_html_to_markdown_pipes_escaped():
    html = "<table><tr><td>a|b</td><td>c</td></tr><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>"
    md = table_rec.html_to_markdown(html)
    assert "a\\|b" in md


def test_html_to_markdown_empty():
    assert table_rec.html_to_markdown("") is None
