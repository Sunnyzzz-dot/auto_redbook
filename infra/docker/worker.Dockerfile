FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY apps/worker/requirements.txt ./apps/worker/requirements.txt

WORKDIR /app/apps/worker
RUN pip install --upgrade pip && pip install -r requirements.txt

WORKDIR /app
COPY apps/worker ./apps/worker

WORKDIR /app/apps/worker

CMD ["python", "-u", "-m", "worker.main"]
