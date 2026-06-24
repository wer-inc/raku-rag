#!/usr/bin/env bash
# Provision a single-VM sales/demo environment for raku-rag on Ubuntu 24.04 (Noble).
#
# Stands up the SAME stack the verified scripts/demo/demo_up.sh runs — Postgres+pgvector,
# the Python answer-service, the NestJS API and the Next.js web — as persistent systemd
# services behind an nginx reverse proxy, so a prospect can reach it at http://<public-ip>/.
#
# Idempotent: safe to re-run. Reseeds the curated 東洋精機 demo KB to a pristine state on every
# answer-service (re)start, so the demo always opens clean.
#
#   sudo REPO_DIR=/opt/raku-rag bash deploy/sales-vm/provision.sh
#
# Auth: keeps the dev-token issuer (HMAC) for a controlled demo — NOT production Cognito. Run behind
# a restricted security group / shareable link. The AI core is the offline deterministic stack (no
# Bedrock); set RAKU_RUNTIME_PROFILE=production + Bedrock creds later for semantic-quality answers.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/raku-rag}"
RUN_USER="${RUN_USER:-raku}"                 # unprivileged user the services run as
WEB_PORT="${WEB_PORT:-3002}"
API_PORT="${API_PORT:-3000}"
AS_PORT="${AS_PORT:-8088}"
PG_DB="${PG_DB:-raku_demo}"
PG_URL="postgresql://raku:raku@127.0.0.1:5432/${PG_DB}"   # pragma: allowlist secret -- local-only demo DB credential
# Real (non-default) shared secrets. Override in the environment for a non-throwaway env.
TOKEN_SECRET="${RAKU_TOKEN_SIGNING_SECRET:-raku-sales-$(openssl rand -hex 12)}"
INTERNAL_SECRET="${RAKU_INTERNAL_AUTH_SECRET:-raku-sales-internal-$(openssl rand -hex 12)}"
THRESH="${RAKU_DEFAULT_SCORE_THRESHOLD:-0.4}"

# Public base URL the browser uses. Auto-detect the EC2 public IP; override with PUBLIC_BASE=https://demo.example.com
PUBLIC_BASE="${PUBLIC_BASE:-}"
if [ -z "$PUBLIC_BASE" ]; then
  ip="$(curl -fsS --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
  PUBLIC_BASE="http://${ip:-localhost}"
fi

say() { printf '\n\033[1;36m[provision]\033[0m %s\n' "$*"; }

say "1/8 OS packages (Postgres 16 + pgvector, Node 20, Python 3.12, nginx)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl ca-certificates gnupg git build-essential nginx openssl python3 python3-venv
# PGDG apt repo guarantees postgresql-16 + the matching pgvector package across Ubuntu releases.
install -d /usr/share/postgresql-common/pgdg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
  -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
  >/etc/apt/sources.list.d/pgdg.list
apt-get update -y
apt-get install -y postgresql-16 postgresql-16-pgvector
# Node 20 via NodeSource (Ubuntu's default node is too old).
if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

say "2/8 service user + repo at ${REPO_DIR}"
id -u "$RUN_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Repo not found at $REPO_DIR — clone it there first (see README), then re-run." >&2
  exit 2
fi
chown -R "$RUN_USER":"$RUN_USER" "$REPO_DIR"

say "3/8 Postgres role + database (${PG_DB})"
systemctl enable --now postgresql
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='raku') THEN
    CREATE ROLE raku LOGIN SUPERUSER PASSWORD 'raku';  -- pragma: allowlist secret -- local-only demo DB credential
  END IF;
END \$\$;
SELECT 'CREATE DATABASE ${PG_DB} OWNER raku' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='${PG_DB}')\gexec
SQL
sudo -u postgres psql -d "$PG_DB" -v ON_ERROR_STOP=1 -f "$REPO_DIR/infra/db/init/01-extensions.sql"

say "4/8 schema migrations (roles/schema/RLS are created idempotently by 0001+)"
sudo -u "$RUN_USER" env POSTGRES_URL="$PG_URL" bash "$REPO_DIR/scripts/pg-migrate.sh" up

say "5/8 build (shared + API dist; web runs in dev mode so the dev-token issuer stays enabled)"
cd "$REPO_DIR"
sudo -u "$RUN_USER" npm ci
sudo -u "$RUN_USER" npm run build:shared
sudo -u "$RUN_USER" npm run build --workspace @raku-rag/api

say "6/8 environment file /etc/raku-rag.env"
cat >/etc/raku-rag.env <<ENV
POSTGRES_URL=${PG_URL}
RAKU_TOKEN_SIGNING_SECRET=${TOKEN_SECRET}
RAKU_INTERNAL_AUTH_SECRET=${INTERNAL_SECRET}
RAKU_DEFAULT_SCORE_THRESHOLD=${THRESH}
ANSWER_SERVICE_URL=http://127.0.0.1:${AS_PORT}
API_PORT=${API_PORT}
WEB_PORT=${WEB_PORT}
AS_PORT=${AS_PORT}
PYTHONPATH=src
# Force-enable the local dev-token issuer for the demo (web runs in dev mode, not NODE_ENV=production).
RAKU_ENABLE_DEV_TOKEN_ISSUER=1
# Browser-visible API base — routed through nginx /v1/ to the NestJS API.
NEXT_PUBLIC_API_BASE=${PUBLIC_BASE}/v1
ENV
chmod 640 /etc/raku-rag.env

say "7/8 systemd services (answer-service, api, web, seed) + nginx"
install_unit() { cat >"/etc/systemd/system/$1"; }

install_unit raku-answer.service <<UNIT
[Unit]
Description=raku-rag answer-service (Python)
After=postgresql.service network-online.target
Wants=postgresql.service
[Service]
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=/etc/raku-rag.env
# --reset-demo-db --seed makes every (re)start return to a pristine curated demo state.
ExecStart=/usr/bin/python3 apps/answer-service/server.py --reset-demo-db --seed --port \${AS_PORT}
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT

install_unit raku-seed.service <<UNIT
[Unit]
Description=raku-rag curated demo KB seed (18 docs + trouble-case graphs)
After=raku-answer.service
Requires=raku-answer.service
[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=/etc/raku-rag.env
# Wait for the answer-service port, then seed the curated KB (logic in seed-wait.sh to avoid
# systemd/shell escaping fragility for the wait loop).
ExecStart=/usr/bin/env bash ${REPO_DIR}/deploy/sales-vm/seed-wait.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT

install_unit raku-api.service <<UNIT
[Unit]
Description=raku-rag NestJS API
After=raku-answer.service network-online.target
Wants=raku-answer.service
[Service]
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=/etc/raku-rag.env
ExecStart=/usr/bin/node --enable-source-maps apps/api/dist/apps/api/src/main
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT

install_unit raku-web.service <<UNIT
[Unit]
Description=raku-rag Next.js web (dev mode)
After=raku-api.service network-online.target
Wants=raku-api.service
[Service]
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
EnvironmentFile=/etc/raku-rag.env
ExecStart=/usr/bin/npm run dev:web
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/nginx/sites-available/raku-rag <<NGINX
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 50m;

    # NestJS API (versioned at /v1). Browser calls <host>/v1/... ; preserve the /v1 prefix.
    location /v1/ {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Everything else → Next.js web (serves the UI and its /api/dev-token route).
    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/raku-rag /etc/nginx/sites-enabled/raku-rag
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

say "8/8 enable + start services"
systemctl daemon-reload
systemctl enable --now raku-answer.service raku-api.service raku-web.service raku-seed.service
systemctl restart raku-seed.service || true   # (re)seed against the now-running answer-service

cat <<DONE

\033[1;32m✓ Sales demo is provisioning.\033[0m
  Open:   ${PUBLIC_BASE}/
  Status: systemctl status raku-answer raku-api raku-web
  Logs:   journalctl -u raku-answer -u raku-api -u raku-web -f
  Reseed: systemctl restart raku-answer && systemctl restart raku-seed
DONE
