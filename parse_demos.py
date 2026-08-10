import time
import os
from pathlib import Path
from markitdown import MarkItDown

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "out" / "markitdown"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEMO_FILES = ["demo.docx", "demo.pdf", "demo.pptx", "demo.xlsx"]

md = MarkItDown()
totals = {}

for filename in DEMO_FILES:
    filepath = ROOT / filename
    if not filepath.exists():
        print(f"[SKIP] {filename} not found")
        continue

    t0 = time.perf_counter()
    result = md.convert(str(filepath))
    elapsed = time.perf_counter() - t0

    out_name = f"{filepath.stem}.{filepath.suffix.lstrip('.')}.md"
    out_path = OUT_DIR / out_name
    out_path.write_text(result.text_content, encoding="utf-8")

    totals[filename] = elapsed
    print(f"[OK] {filename} -> {out_path}  ({elapsed:.3f}s)")

print()
print("=" * 50)
print("Parse timing summary:")
for f, t in totals.items():
    print(f"  {f:12s}  {t:.3f}s")
total = sum(totals.values())
print(f"  {'TOTAL':12s}  {total:.3f}s")
