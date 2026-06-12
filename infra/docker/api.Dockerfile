FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages/agent_core ./packages/agent_core
COPY apps/api/requirements.txt ./apps/api/requirements.txt

WORKDIR /app/apps/api
RUN pip install --upgrade pip && pip install -r requirements.txt

WORKDIR /app
COPY apps/api ./apps/api

WORKDIR /app/apps/api
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
