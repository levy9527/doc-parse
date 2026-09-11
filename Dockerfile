FROM docker.m.daocloud.io/python:3.12-slim

WORKDIR /app

# libgomp1: onnxruntime 在 slim 上需要
# libgl1/libglib2.0-0: opencv-python(cv2) 在 slim 上 import 需要 libGL
# 先切清华 debian 镜像，避免官方源国内 502
RUN sed -i \
      's|URIs: http://deb.debian.org/debian-security|URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security|; \
       s|URIs: http://deb.debian.org/debian|URIs: https://mirrors.tuna.tsinghua.edu.cn/debian|' \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 \
      libgl1 \
      libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 用 uv 安装（快）。uv 仅首次经 tuna pip 装一下；之后依赖 + 包本身都交给 uv。
# PIP_INDEX_URL 必须设：UV_INDEX_URL 只管 uv，管不到下面这行 pip install uv，
#   否则它会走 pypi.org 默认源（国内很慢）。
# UV_CACHE_DIR 显式写出，配合下面的 BuildKit cache mount 跨构建复用已下载的 wheel。
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_SYSTEM_PYTHON=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_CACHE_DIR=/root/.cache/uv
RUN pip install -q uv

# ------------------------------------------------------------
# 依赖层：只读 pyproject.toml
#   顺序很关键 —— 必须放在 COPY src/ 之前。原写法先 COPY 源码再安装，
#   导致改任何一行代码都会让整个依赖安装层失效、重下约 2GB 依赖。
#   --mount=type=cache 让 uv 的下载缓存在构建之间复用：即便本层因
#   pyproject.toml 变更而失效，wheel 也从本地缓存取，不再走公网。
# ------------------------------------------------------------
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    python -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print(chr(10).join(list(d.get('project',{}).get('dependencies',[]))+list(d.get('build-system',{}).get('requires',[]))))" > /tmp/requirements.txt \
    && cat /tmp/requirements.txt \
    && uv pip install -r /tmp/requirements.txt

# ------------------------------------------------------------
# 项目层：拷源码 + 只装项目本身
#   依赖已在上一层装好：--no-deps 跳过依赖解析，--no-build-isolation
#   复用上一层装好的 setuptools，避免再访问网络。
#   改源码只需重跑这一层，秒级完成。
# ------------------------------------------------------------
COPY .env.sample ./
COPY src/ ./src/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-deps --no-build-isolation .

# 离线模型预置：构建期下载并固化 ONNX 模型（运行期不再联网）
# 注意：当前引擎用各包默认模型缓存路径；此步把模型拷到 /app/models 供审计/后续注入。
RUN --mount=type=cache,target=/root/.cache/uv \
    python scripts/download_models.py /app/models || echo "WARN: model download failed (build not offline)"

EXPOSE 8000

CMD ["uvicorn", "docparse.server:app", "--host", "0.0.0.0", "--port", "8000"]
