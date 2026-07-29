# Deployment Guide

How to run the Tech Desk Intelligence platform on a single AWS EC2 instance.
Two supported paths: a native **systemd** service (recommended) or **Docker**.

> **Architecture note — run one process.** Background jobs, the in-memory job
> registry that powers the Activity view, and the APScheduler all live inside a
> single process. Do **not** scale to multiple workers/replicas without first
> moving those to a shared store (Redis/Celery + Postgres). Vertical scaling
> (a bigger instance) is the supported way to add capacity today.

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

The script installs system dependencies, creates the `techdesk` service user,
builds a virtualenv under `/opt/techdesk/venv`, installs the app, seeds
`/opt/techdesk/app/.env`, and starts the `techdesk` systemd service bound to
`127.0.0.1:8080`.

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

```bash
cp .env.example .env      # edit with your OPENAI_API_KEY and settings
docker compose up -d --build
docker compose logs -f
```

The container binds to `127.0.0.1:8080`; front it with nginx exactly as above.
Data persists in the `tech-desk-data` named volume.

## 4. Configuration reference

All configuration is environment-driven (`.env` or real env vars). Key settings:

| Variable | Purpose | Production guidance |
|---|---|---|
| `OPENAI_API_KEY` | LLM provider key | Required. Keep secret; `.env` is `chmod 600`. |
| `LLM_PROVIDER` | `openai`/`anthropic`/… | Match your key. |
| `OPENAI_MODEL` | Model id | e.g. `gpt-4o`. |
| `ENV` | Environment name | Set to `production` (hides error detail, disables `/api/diagnostics`). |
| `TECH_DESK_DATA_DIR` | DB + reports + logs | A persistent path, e.g. `/opt/techdesk/data`. |
| `CORS_ORIGINS` | Allowed browser origins | Set to your domain, **not** `*`, if calling the API cross-origin. |
| `SCHEDULER_ENABLED` | Automated daily/weekly/monthly runs | `true` to enable unattended reports. |
| `LOG_LEVEL` | Logging verbosity | `INFO`. |

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
cd /path/to/checkout && git pull && sudo bash deploy/deploy.sh
```

### Backups

Everything lives under `TECH_DESK_DATA_DIR`. Back it up (the SQLite DB uses WAL,
so copy `tech_desk.db*`):

```bash
sudo systemctl stop techdesk
sudo tar czf techdesk-backup-$(date +%F).tgz -C /opt/techdesk data
sudo systemctl start techdesk
```

## 6. Security checklist

- [ ] Port `8080` is bound to localhost; only nginx is public.
- [ ] TLS enabled; HTTP redirects to HTTPS.
- [ ] Security group restricts inbound to known CIDRs.
- [ ] `.env` is `chmod 600` and never committed.
- [ ] `ENV=production` so internal errors aren't leaked and diagnostics are off.
- [ ] Basic auth (or an upstream SSO proxy) protects the dashboard.
