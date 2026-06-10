# API Surface

Base URL: `http://localhost:8000`

## Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

## Settings

- `POST /api/model-keys`
- `GET /api/model-keys`
- `POST /api/xhs-accounts`
- `GET /api/xhs-accounts`

## Agent

- `POST /api/agent/runs`
- `GET /api/agent/runs/{run_id}`
- `POST /api/agent/runs/{run_id}/regenerate`
- `PATCH /api/drafts/{draft_id}`

## Publishing

- `POST /api/publish-jobs`
- `GET /api/publish-jobs/{job_id}`
- `POST /api/publish-jobs/{job_id}/approve`
- `WS /api/workers/connect`
- `WS /api/browser-sessions/{session_id}`

