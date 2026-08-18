# Deployment Guide

How to run the Tech Desk Intelligence platform on a single AWS EC2 instance.
Two supported paths: a native **systemd** service (recommended) or **Docker**.

> **Architecture note — one app process today.** Background jobs, the in-memory
> job registry that powers the Activity view, and the APScheduler all live inside
> a single process. A single instance handles many concurrent users comfortably
> — and with PostgreSQL (below) it handles many concurrent **writers** too.
> Running **multiple app instances** additionally requires externalizing three
> things (see [Database & scaling](#database--scaling)): the database (Postgres),
> report file storage (shared EFS/S3), and jobs + scheduler (a shared queue).

---

## 1. Provision the instance

- **AMI:** Ubuntu 22.04 LTS (or Amazon Linux 2023 with `dnf` equivalents).
- **Size:** `t3.small` is a comfortable starting point (PDF rendering + LLM I/O).
- **Storage:** 20 GB gp3 is plenty; reports and the SQLite DB are small.
- **Security group:**
  - Inbound `443` (and `80` for the ACME/redirect) from your allowed CIDRs.
  - Inbound `22` from your admin IP only.
  - **Do not** expose port `8080` publicly — it stays bound to localhost.

## 2. Deploy with systemd (recommended)

```bash
# On the instance, as a sudo-capable user:
git clone <your-repo-url> techdesk && cd techdesk
sudo bash deploy/deploy.sh
```

The script installs system dependencies (including Node.js, used only to build
the frontend), creates the `techdesk` service user, builds the React frontend
(`frontend/` → `npm ci && npm run build`), builds a virtualenv under
`/opt/techdesk/venv`, installs the app, seeds `/opt/techdesk/app/.env`, and
starts the `techdesk` systemd service bound to `127.0.0.1:8080`.

Then set your real configuration:

```bash
sudo -e /opt/techdesk/app/.env      # set OPENAI_API_KEY, LLM_PROVIDER, CORS_ORIGINS, etc.
sudo systemctl restart techdesk
systemctl status techdesk           # verify it's active
curl -s http://127.0.0.1:8080/api/health
```

### Put nginx in front (TLS + optional auth)

```bash
sudo apt-get install -y nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/techdesk
sudo ln -sf /etc/nginx/sites-available/techdesk /etc/nginx/sites-enabled/techdesk
sudo nginx -t && sudo systemctl reload nginx

# TLS via Let's Encrypt:
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d techdesk.example.com

# Optional HTTP basic auth (the app itself has no login):
sudo apt-get install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd techdesk
# then uncomment the auth_basic lines in the nginx config and reload
```

## 3. Deploy with Docker (alternative)

Docker doesn't require Ubuntu — install the Docker Engine + Compose plugin for
whatever distro you're on, then everything else is identical:

```bash
# Ubuntu 22.04:
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Amazon Linux 2023:
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo mkdir -p /usr/libexec/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/libexec/docker/cli-plugins/docker-compose
sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
```

Then, from a checkout of the repo on the instance:

```bash
git clone <your-repo-url> techdesk && cd techdesk
sudo bash deploy/deploy-docker.sh   # seeds .env on first run — edit it, then re-run
```

`deploy/deploy-docker.sh` is the Docker-path equivalent of `deploy/deploy.sh`
(the systemd path) — it seeds `.env` from the example on first run, then on
subsequent runs builds the image (frontend build is baked into the
multi-stage `Dockerfile`) and health-checks the container. It's safe to re-run
after a `git pull` to deploy new code. Equivalent manual commands:

```bash
cp .env.example .env      # edit with your OPENAI_API_KEY and settings
docker compose up -d --build
docker compose logs -f
```

The container binds to `127.0.0.1:8080`; front it with nginx exactly as above.
Data persists in the `tech-desk-data` named volume.

The app runs as a non-root `techdesk` user (uid `999`) inside the container,
and writes back to `config/tech_desks.yaml` when new vendors are auto-tracked.
On a fresh clone, the host `config/` directory is owned by whatever user ran
`git clone` (e.g. `ubuntu`), which the container user can't write to. Fix once
after cloning:

```bash
sudo chown -R 999:999 config/
```



```bash
# in .env:
DATABASE_URL=postgresql+psycopg://techdesk:techdesk@db:5432/techdesk

docker compose --profile postgres up -d --build
```

This starts a local Postgres 16 container alongside the app. For production on
EC2, prefer **AWS RDS** and point `DATABASE_URL` at it instead of the compose
`db` service.

## 4. Configuration reference

All configuration is environment-driven (`.env` or real env vars). Key settings:

| Variable | Purpose | Production guidance |
|---|---|---|
| `OPENAI_API_KEY` | LLM provider key | Required. Keep secret; `.env` is `chmod 600`. |
| `LLM_PROVIDER` | `openai`/`anthropic`/… | Match your key. |
| `OPENAI_MODEL` | Model id | e.g. `gpt-4o`. |
| `ENV` | Environment name | Set to `production` (hides error detail, disables `/api/diagnostics`). |
| `TECH_DESK_DATA_DIR` | Reports + logs (+ SQLite file if used) | A persistent path, e.g. `/opt/techdesk/data`. |
| `DATABASE_URL` | Database connection | Empty = SQLite fallback. Set to `postgresql+psycopg://…` for concurrent writers. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | Postgres pool sizing | Defaults `5` / `10` are fine for one instance. |
| `CORS_ORIGINS` | Allowed browser origins | Set to your domain, **not** `*`, if calling the API cross-origin. |
| `SCHEDULER_ENABLED` | Automated daily/weekly/monthly runs | `true` to enable unattended reports. |
| `LOG_LEVEL` | Logging verbosity | `INFO`. |

## Database & scaling

The app uses SQLAlchemy and runs on either backend:

| Backend | When | Setup |
|---|---|---|
| **SQLite** (default) | Single instance, light write volume | None — a file is created in `TECH_DESK_DATA_DIR`. |
| **PostgreSQL** | Many concurrent writers/users, managed backups/HA | Set `DATABASE_URL`; install the driver. |

SQLite is the automatic fallback: if `DATABASE_URL` is empty, the app uses the
local file. Set `DATABASE_URL` to switch to Postgres — no code changes.

### Point the app at PostgreSQL

```bash
# Install the driver (in the app's virtualenv)
/opt/techdesk/venv/bin/pip install "psycopg[binary]"
# or from the repo:  pip install -e ".[postgres]"

# In /opt/techdesk/app/.env
DATABASE_URL=postgresql+psycopg://techdesk:password@db-host:5432/techdesk
DB_POOL_SIZE=5          # connections held open per app process
DB_MAX_OVERFLOW=10      # extra burst connections
```

Provision Postgres with **AWS RDS** (managed backups, failover) or a local
server. Create the database and user, then restart the app — tables are created
automatically on first startup. Confirm the active backend:

```bash
curl -s http://127.0.0.1:8080/api/health | grep -o '"database":"[^"]*"'
```

### Running more than one app instance

Postgres removes the database write bottleneck, but three things are still
per-process and must be externalized before load-balancing multiple instances:

1. **Report files** — written under `TECH_DESK_DATA_DIR/reports/`. Put this on
   shared storage (**EFS**) or object storage (**S3**) so any instance can serve
   any report.
2. **Background jobs** — the job registry is in-memory, so a job on instance A is
   invisible to instance B. Move to a shared queue/worker (**Celery/RQ + Redis**).
3. **Scheduler** — APScheduler would fire on every instance. Run it as a single
   dedicated worker, or add a leader lock (e.g. Postgres advisory lock).

Until then, the supported topology is **one app instance + PostgreSQL**, which
already serves many concurrent users and writers reliably. Scale that instance
vertically as needed.

## 5. Operations

```bash
# Logs
journalctl -u techdesk -f                 # systemd
docker compose logs -f                      # docker
tail -f /opt/techdesk/data/logs/tech-desk.log

# Health / readiness (readiness checks DB + disk + key)
curl -s http://127.0.0.1:8080/api/health
curl -s http://127.0.0.1:8080/api/ready

# Update to a new version
cd /path/to/checkout && git pull && sudo bash deploy/deploy.sh          # systemd
cd /path/to/checkout && git pull && sudo bash deploy/deploy-docker.sh  # docker
```

### Backups

**SQLite (default):** everything lives under `TECH_DESK_DATA_DIR`. Copy the WAL
set while the app is stopped:

```bash
sudo systemctl stop techdesk
sudo tar czf techdesk-backup-$(date +%F).tgz -C /opt/techdesk data
sudo systemctl start techdesk
```

**PostgreSQL:** back up with `pg_dump` (or enable automated RDS snapshots) and
separately archive `TECH_DESK_DATA_DIR/reports/` for the generated files.

## 6. Security checklist

- [ ] Port `8080` is bound to localhost; only nginx is public.
- [ ] TLS enabled; HTTP redirects to HTTPS.
- [ ] Security group restricts inbound to known CIDRs.
- [ ] `.env` is `chmod 600` and never committed.
- [ ] `ENV=production` so internal errors aren't leaked and diagnostics are off.
- [ ] Basic auth (or an upstream SSO proxy) protects the dashboard.
