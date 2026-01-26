FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# system deps for Pillow + basic build tooling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# install deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# copy app
COPY . /app

# create dirs for runtime state
RUN mkdir -p /app/media

EXPOSE 8000

# ROOT_PATH is used when app is served under a subpath (e.g. /smarttherm/webkb)
ENV ROOT_PATH=""

CMD ["bash", "-lc", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]