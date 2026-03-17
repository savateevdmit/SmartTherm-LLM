FROM nvcr.io/nvidia/pytorch:25.02-py3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-turbo8-dev \
    zlib1g-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-input -r /app/requirements.txt

RUN python -c "import torch; print('torch', torch.__version__); print('cuda', torch.version.cuda); print('arch_list', torch.cuda.get_arch_list())"

COPY . /app

RUN mkdir -p /app/media /app/data /models

EXPOSE 8052

CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port 8052 --proxy-headers"]
