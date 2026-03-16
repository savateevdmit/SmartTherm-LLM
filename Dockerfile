FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3-pip \
    build-essential \
    libjpeg-turbo8-dev \
    zlib1g-dev \
    git \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel --break-system-packages && \
    python -m pip install --no-input --pre --only-binary=:all: \
      --index-url https://download.pytorch.org/whl/nightly/cu128 \
      torch torchvision torchaudio \
      --break-system-packages && \
    python -m pip install --no-input \
      --index-url https://pypi.org/simple \
      -r /app/requirements.txt \
      --break-system-packages

RUN python -c "import torch; print('torch', torch.__version__); print('cuda', torch.version.cuda); print('arch_list', torch.cuda.get_arch_list())"

COPY . /app

RUN mkdir -p /app/media /app/data /models

EXPOSE 8052

CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port 8052 --proxy-headers"]
