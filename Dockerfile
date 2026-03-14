FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    git \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

# Install torch CUDA wheels (cu124) for embeddings
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-input --index-url https://download.pytorch.org/whl/cu124 torch && \
    python -m pip install --no-input --index-url https://pypi.org/simple -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/media /app/data /models

EXPOSE 8052

CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port 8052 --proxy-headers"]