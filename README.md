# Red Book Agent

Self-hosted Xiaohongshu note publishing agent built with Vue 3, FastAPI, a custom ReAct runtime, Doubao models, PostgreSQL, object storage, and a Playwright publishing worker.

The project is designed for multi-user, multi-account operations. It supports draft review, local browser login persistence, remote browser handoff for verification or risk-control pages, and optional automatic final publish.

## Modules

- `apps/web`: Vue 3 operator console.
- `apps/api`: FastAPI API server, database models, Agent orchestration, model clients, worker dispatch.
- `apps/worker`: Playwright publishing worker that connects back to the API over WebSocket.
- `packages/agent_core`: framework-free ReAct runtime, tool registry, tracing, retries, and guardrails.
- `infra`: local PostgreSQL, MinIO, Redis, and migration assets.

## Quick Start

1. Copy environment files.

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env
```

2. Start backing services.

```bash
docker compose -f infra/docker-compose.yml up -d
```

3. Start the API.

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

4. Start the web app.

```bash
cd apps/web
npm install
npm run dev
```

5. Start a local publishing worker.

```bash
cd apps/worker
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
playwright install chromium
python -m worker.main
```

## Product Flow

```text
One-line instruction
-> intent extraction
-> prompt refinement
-> 3 titles
-> body
-> hashtags
-> image prompts
-> Seedream image generation
-> safety review
-> human editing/review
-> Playwright fills creator page
-> human approval or automatic publish
-> publish audit record
```

## Safety Boundary

The worker never attempts to bypass login, CAPTCHA, or platform risk-control flows. When such a page is detected, the job moves to `requires_human_intervention` and exposes a remote browser-control session for the account owner.
