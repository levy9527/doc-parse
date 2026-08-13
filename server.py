from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile

from doc_parser import parse

app = FastAPI(title="doc-parse", description="文档解析为 Markdown 的 HTTP 服务")

TMP_ROOT = Path(tempfile.gettempdir()) / "doc-parse"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/parse")
async def parse_file(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    original = Path(file.filename).name
    suffix = Path(original).suffix.lower()

    workdir = TMP_ROOT / uuid.uuid4().hex
    workdir.mkdir(parents=True, exist_ok=True)
    filepath = workdir / (f"upload{suffix}" if suffix else f"upload_{original}")

    try:
        with open(filepath, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as exc:
        await file.close()
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"写入临时文件失败: {exc}")
    finally:
        await file.close()

    try:
        text = parse(filepath)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return {"filename": original, "text": text}
