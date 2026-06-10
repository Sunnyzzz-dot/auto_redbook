CREATE TABLE IF NOT EXISTS users (
  id VARCHAR(36) PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(50) NOT NULL DEFAULT 'operator',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS model_keys (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider VARCHAR(50) NOT NULL DEFAULT 'volcengine_ark',
  encrypted_api_key TEXT NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS xhs_accounts (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  display_name VARCHAR(120) NOT NULL,
  bound_worker_id VARCHAR(120),
  browser_profile_id VARCHAR(120) NOT NULL,
  login_status VARCHAR(50) NOT NULL DEFAULT 'unknown',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  instruction TEXT NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'pending',
  config JSONB NOT NULL DEFAULT '{}',
  failure_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_steps (
  id VARCHAR(36) PRIMARY KEY,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  step VARCHAR(100) NOT NULL,
  thought_summary TEXT NOT NULL,
  action VARCHAR(120) NOT NULL,
  action_input JSONB NOT NULL DEFAULT '{}',
  observation JSONB NOT NULL DEFAULT '{}',
  status VARCHAR(50) NOT NULL,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS draft_notes (
  id VARCHAR(36) PRIMARY KEY,
  run_id VARCHAR(36) UNIQUE NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title_candidates JSONB NOT NULL DEFAULT '[]',
  selected_title VARCHAR(120) NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  hashtags JSONB NOT NULL DEFAULT '[]',
  style VARCHAR(120) NOT NULL DEFAULT '',
  target_audience VARCHAR(255) NOT NULL DEFAULT '',
  safety_report JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_images (
  id VARCHAR(36) PRIMARY KEY,
  draft_id VARCHAR(36) NOT NULL REFERENCES draft_notes(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  prompt TEXT NOT NULL,
  seed INTEGER,
  ratio VARCHAR(20) NOT NULL DEFAULT '3:4',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_selected BOOLEAN NOT NULL DEFAULT TRUE,
  provider_response JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_jobs (
  id VARCHAR(36) PRIMARY KEY,
  draft_id VARCHAR(36) NOT NULL REFERENCES draft_notes(id) ON DELETE CASCADE,
  account_id VARCHAR(36) NOT NULL REFERENCES xhs_accounts(id) ON DELETE CASCADE,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  publish_mode VARCHAR(50) NOT NULL DEFAULT 'manual_approve',
  status VARCHAR(60) NOT NULL DEFAULT 'queued',
  result_url TEXT,
  screenshot_url TEXT,
  failure_reason TEXT,
  worker_id VARCHAR(120),
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
  id VARCHAR(120) PRIMARY KEY,
  machine_name VARCHAR(255) NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'offline',
  version VARCHAR(50) NOT NULL DEFAULT '0.1.0',
  capabilities JSONB NOT NULL DEFAULT '{}',
  last_seen_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS browser_sessions (
  id VARCHAR(36) PRIMARY KEY,
  job_id VARCHAR(36) NOT NULL REFERENCES publish_jobs(id) ON DELETE CASCADE,
  status VARCHAR(50) NOT NULL DEFAULT 'active',
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action VARCHAR(120) NOT NULL,
  target_type VARCHAR(120) NOT NULL,
  target_id VARCHAR(120) NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_id ON agent_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_publish_jobs_user_id ON publish_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_xhs_accounts_user_id ON xhs_accounts(user_id);

