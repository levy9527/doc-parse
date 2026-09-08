"""构建期离线模型预置脚本。

作用：
  1) 实例化 rapidocr + table_cls + wired_table_rec + lineless_table_rec，
     触发各包把 ONNX 模型从 modelscope 下载到 <site-packages>/<pkg>/models/（首次）。
  2) 把这些已下载的模型拷贝到 out_dir（默认 /app/models），并写 manifest.json。

用法：
  python scripts/download_models.py [out_dir]
容器内执行一次后即可离线运行（运行期不联网）。

注：rapidocr 默认下载 v6 small 三件套；表格三包从 RapidTable 下载 wired/unet、
lineless(lore) 与 table_cls(yolo)。文件随包版本变化，本脚本用 glob 抓取而非硬编码名。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import importlib

# 各包内的模型缓存目录（相对包根）
PKG_MODEL_REL = ["models"]
PACKAGES = ["rapidocr", "table_cls", "wired_table_rec", "lineless_table_rec"]


def _pkg_dir(name: str) -> Path:
    return Path(importlib.import_module(name).__file__).resolve().parent


def _warm():
    # 首次实例化会下载模型
    from rapidocr import RapidOCR

    RapidOCR()
    from table_cls import TableCls

    TableCls()
    from wired_table_rec.main import WiredTableInput, WiredTableRecognition

    WiredTableRecognition(WiredTableInput())
    from lineless_table_rec.main import LinelessTableInput, LinelessTableRecognition

    LinelessTableRecognition(LinelessTableInput())


def _collect() -> list[tuple[Path, str]]:
    """返回 [(源文件, 目标相对名)]，目标相对名含包名前缀避免重名。"""
    found: list[tuple[Path, str]] = []
    for pkg in PACKAGES:
        base = _pkg_dir(pkg)
        for rel in PKG_MODEL_REL:
            d = base / rel
            if not d.exists():
                continue
            for f in sorted(d.glob("*.onnx")):
                found.append((f, f"{pkg}/{f.name}"))
    return found


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/app/models")
    print(f"[download_models] warming engines to fetch models...", flush=True)
    _warm()

    models = _collect()
    if not models:
        print("[download_models] no onnx found in package models dirs", file=sys.stderr)
        return 1

    manifest: dict[str, dict] = {}
    for src, rel in models:
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        h = hashlib.sha256(dst.read_bytes()).hexdigest()
        manifest[rel] = {"sha256": h, "size": dst.stat().st_size, "source": str(src)}
        print(f"  saved {dst}")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    total = sum(v["size"] for v in manifest.values())
    print(f"[download_models] done: {len(manifest)} models, {total/1e6:.1f} MB -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
