import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
OUT_DIR = ROOT.parent / "out" / "liteparse"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEMO_FILES = ["demo.docx", "demo.pdf", "demo.pptx", "demo.xlsx"]

totals = {}

for filename in DEMO_FILES:
    filepath = ROOT / filename
    if not filepath.exists():
        print(f"[SKIP] {filename} not found")
        continue

    out_name = f"{filepath.stem}.{filepath.suffix.lstrip('.')}.md"
    out_path = OUT_DIR / out_name

    t0 = time.perf_counter()
    result = subprocess.run(
        ["lit", "parse", str(filepath), "--no-ocr", "--format", "markdown",
         "-o", str(out_path), "-q"],
        capture_output=True, text=True, timeout=120,
    )
    elapsed = time.perf_counter() - t0

    if result.returncode != 0:
        print(f"[FAIL] {filename}: {result.stderr.strip()}")
        continue

    totals[filename] = elapsed
    print(f"[OK] {filename} -> {out_path}  ({elapsed:.3f}s)")

print()
print("=" * 50)
print("Parse timing summary (liteparse):")
for f, t in totals.items():
    print(f"  {f:12s}  {t:.3f}s")
total = sum(totals.values())
print(f"  {'TOTAL':12s}  {total:.3f}s")
