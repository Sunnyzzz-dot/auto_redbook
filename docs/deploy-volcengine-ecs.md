# Volcengine ECS production demo deployment

This guide deploys the full demo stack on one Ubuntu ECS instance with Docker Compose:

- PostgreSQL
- Redis
- MinIO
- FastAPI API
- Vue web app
- Playwright worker
- Nginx HTTPS gateway

The deployment uses a self-signed HTTPS certificate and exposes only ports `80` and `443`
for the app. Keep port `22` open only for SSH access.

## 1. Prepare the server

Run as `root` or a sudo-enabled user:

```bash
apt update
apt install -y git curl ca-certificates openssl docker.io docker-compose-plugin
systemctl enable --now docker
```

In the Volcengine security group, allow only:

```text
22
80
443
```

Do not expose PostgreSQL, Redis, MinIO, API, or Vite ports to the public internet.

## 2. Clone the project

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/Sunnyzzz-dot/auto_redbook.git redbook-agent
cd /opt/redbook-agent
```

## 3. Create production environment

```bash
cp .env.production.example .env.production
nano .env.production
```

Replace at least these values:

```env
APP_SECRET_KEY=use-a-long-random-secret
POSTGRES_PASSWORD=use-a-strong-postgres-password
MINIO_ROOT_PASSWORD=use-a-strong-minio-password
S3_SECRET_ACCESS_KEY=use-the-same-value-as-MINIO_ROOT_PASSWORD
DATABASE_URL=postgresql+asyncpg://redbook:use-a-strong-postgres-password@postgres:5432/redbook_agent
SYNC_DATABASE_URL=postgresql://redbook:use-a-strong-postgres-password@postgres:5432/redbook_agent
PUBLIC_UPLOAD_BASE_URL=https://YOUR_SERVER_PUBLIC_IP/uploads
CORS_ORIGINS=https://YOUR_SERVER_PUBLIC_IP
WORKER_TOKEN=use-a-long-random-worker-token
ARK_API_KEY=your-volcengine-ark-api-key
DOUBAO_TEXT_MODEL=your-text-model-endpoint-id
DOUBAO_IMAGE_MODEL=your-image-model-endpoint-id
```

If the password contains reserved URL characters such as `@`, `/`, `:`, or `#`,
URL-encode it inside `DATABASE_URL` and `SYNC_DATABASE_URL`.

`WORKER_ASSET_BASE_URL=http://api:8000` should stay internal. It lets the worker
download generated images from the API container without hitting the self-signed
public HTTPS endpoint.

The production worker runs Chromium in headless mode by default:

```env
HEADLESS=true
PUBLISH_TIMEOUT_SECONDS=300
```

Remote takeover still works because it streams Playwright screenshots and sends
mouse/keyboard events back to the page. A physical monitor or desktop session is
not required.

`PUBLISH_TIMEOUT_SECONDS` is the worker-side safety timeout for one publish job.
If the worker cannot finish within this time, it reports the job as failed with
`publish_timeout` instead of leaving it stuck in `sent_to_worker`.

## 4. Create a self-signed certificate

```bash
mkdir -p infra/certs
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout infra/certs/server.key \
  -out infra/certs/server.crt \
  -subj "/CN=YOUR_SERVER_PUBLIC_IP"
```

Replace `YOUR_SERVER_PUBLIC_IP` with the ECS public IP.

Browsers will show a certificate warning. Accept it for this demo. When a real
domain is available, replace this with a trusted certificate.

## 5. Start all services

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production up -d --build
```

Check service status:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production ps
```

Follow logs:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production logs -f api
docker compose -f infra/docker-compose.prod.yml --env-file .env.production logs -f worker
docker compose -f infra/docker-compose.prod.yml --env-file .env.production logs -f nginx
```

Confirm that the worker registered with the API:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production exec postgres \
  psql -U redbook -d redbook_agent \
  -c "select id, machine_name, status, last_seen_at from workers order by last_seen_at desc;"
```

The expected worker id should match `WORKER_ID` in `.env.production`.

## 6. Verify the deployment

Health check:

```bash
curl -k https://YOUR_SERVER_PUBLIC_IP/healthz
```

Open the web app:

```text
https://YOUR_SERVER_PUBLIC_IP
```

Then verify:

- Register and log in.
- Save a Volcengine Ark model key, or use the `ARK_API_KEY` fallback from `.env.production`.
- Generate a note and images.
- Bind a Xiaohongshu account.
- Create a publish job.
- Use remote takeover to complete Xiaohongshu login or risk control.
- Test manual publish and auto publish.
- Restart the stack and confirm data, generated images, and browser login state remain.

Restart test:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production restart
```

## 7. Update the demo

After pushing changes to GitHub:

```bash
cd /opt/redbook-agent
git pull
docker compose -f infra/docker-compose.prod.yml --env-file .env.production up -d --build
```

## 8. Stop or reset

Stop containers while keeping data:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production down
```

Delete all persisted demo data:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env.production down -v
```

Use `down -v` carefully. It removes PostgreSQL data, generated assets, and worker
browser profiles.
