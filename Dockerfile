FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    XDG_STATE_HOME=/tmp/appstate

WORKDIR /app

# api-server deps first (better layer caching)
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# musicdl deps (manylinux wheels only, no compilation needed on slim)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# musicdl library (editable not needed in image; regular install)
COPY setup.py README.md MANIFEST.in ./
COPY musicdl/ ./musicdl/
RUN pip install --no-cache-dir .

# api server code + webgui（同一镜像跑两个容器：api:3003 / webgui:3004；
# webgui 的 fastapi/uvicorn/pydantic 是 server 依赖的子集，不增加体积）
COPY server/ ./server/
COPY examples/musicdlwebgui/ ./examples/musicdlwebgui/

RUN mkdir -p /tmp/appstate /tmp/kwqq-kuwo /tmp/kwqq-qq

EXPOSE 3003 3004

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3003/healthz', timeout=5)" || exit 1

CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "3003", "--workers", "1"]
