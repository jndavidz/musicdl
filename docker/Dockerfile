FROM python:3.10-slim

# 1. 设置环境变量，防止生成 pyc 和强制刷新缓存
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV REFRESH_VERSION=V1.0.final

# 2. 安装系统依赖，包括 git（必须有 git 才能拉源码手术）
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# 3. 核心手术：直接从源码安装并强行修改
WORKDIR /app
RUN git clone https://github.com/CharlesPikachu/musicdl.git . && \
    # 强制将所有代码中的 Cryptodome 字符替换为 Crypto（递归所有子目录）
    find . -type f -name "*.py" -exec sed -i 's/Cryptodome/Crypto/g' {} + && \
    # 关键：先卸载可能存在的冲突包，然后显式安装 pycryptodome，最后安装当前目录下的“已手术”源码
    pip install --no-cache-dir pycryptodome && \
    pip install --no-cache-dir .

# 4. 物理防线：建立软链接（双保险，防止 Python 导入机制死板）
RUN python -c "import site; import os; sp = site.getsitepackages()[0]; \
    src = os.path.join(sp, 'Crypto'); \
    dst = os.path.join(sp, 'Cryptodome'); \
    os.symlink(src, dst) if os.path.exists(src) and not os.path.exists(dst) else None"

# 5. 设置运行环境
RUN mkdir -p /downloads /root/.musicdl
WORKDIR /downloads

# 运行命令
CMD ["musicdl"]
