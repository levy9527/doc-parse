FROM docker.m.daocloud.io/python:3.12-slim

WORKDIR /app

# poppler: pdftoppm/pdftotext/pdfinfo（渲染 + 文字层探测，规避 MuPDF License）
# libgomp1: onnxruntime 在 slim 上需要
# libgl1/libglib2.0-0: opencv-python(cv2) 在 slim 上 import 需要 libGL
# 先切清华 debian 镜像，避免官方源国内 502
RUN sed -i \
      's|URIs: http://deb.debian.org/debian-security|URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security|; \
       s|URIs: http://deb.debian.org/debian|URIs: https://mirrors.tuna.tsinghua.edu.cn/debian|' \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils \
      libgomp1 \
      libgl1 \
      libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# 用 uv 安装（快）。uv 仅首次经 tuna pip 装一下；之后所有依赖交给 uv。
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_SYSTEM_PYTHON=1 \
    PIP_NO_CACHE_DIR=1
RUN pip install -q uv \
    && uv pip install --no-cache -r requirements.txt \
    && rm -rf /root/.cache/uv

COPY doc_parser.py txt_parser.py config.py ocr.py table_rec.py pdf_pipeline.py server.py ./
COPY scripts/ ./scripts/

# 离线模型预置：构建期下载并固化 ONNX 模型（运行期不再联网）
# 注意：当前引擎用各包默认模型缓存路径；此步把模型拷到 /app/models 供审计/后续注入。
RUN python scripts/download_models.py /app/models || echo "WARN: model download failed (build not offline)"

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
