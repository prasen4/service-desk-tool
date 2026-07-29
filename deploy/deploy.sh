#!/usr/bin/env bash
#
# Provision or update the Tech Desk app on an Ubuntu/Debian EC2 instance.
# Run as root (or with sudo) from a checkout of the repository:
#
#   sudo bash deploy/deploy.sh
#
# It is safe to re-run: it updates the code, dependencies, and service in place.

set -euo pipefail

APP_USER="techdesk"
APP_ROOT="/opt/techdesk"
APP_DIR="${APP_ROOT}/app"
VENV_DIR="${APP_ROOT}/venv"
DATA_DIR="${APP_ROOT}/data"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev \
    shared-mime-info fonts-dejavu-core

echo "==> Creating service user and directories"
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --home "${APP_ROOT}" --shell /usr/sbin/nologin "${APP_USER}"
fi
mkdir -p "${APP_DIR}" "${DATA_DIR}"

echo "==> Syncing application code"
# Copy everything except local data/venv (see rsync excludes).
rsync -a --delete \
    --exclude '.git' --exclude '.venv' --exclude 'data' \
    --exclude '.pytest-data' --exclude '__pycache__' \
    "${REPO_DIR}/" "${APP_DIR}/"

echo "==> Creating / updating virtualenv"
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --upgrade pip
# Include the Postgres driver so DATABASE_URL can be flipped without a reinstall.
# SQLite remains the default when DATABASE_URL is empty.
"${VENV_DIR}/bin/pip" install "${APP_DIR}[postgres]"

if [ ! -f "${APP_DIR}/.env" ]; then
    echo "==> Seeding .env from example (EDIT THIS with your real API key + settings)"
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    sed -i "s#^TECH_DESK_DATA_DIR=.*#TECH_DESK_DATA_DIR=${DATA_DIR}#" "${APP_DIR}/.env"
    sed -i "s#^ENV=.*#ENV=production#" "${APP_DIR}/.env"
fi

echo "==> Setting ownership"
chown -R "${APP_USER}:${APP_USER}" "${APP_ROOT}"
chmod 600 "${APP_DIR}/.env"

echo "==> Installing systemd service"
cp "${APP_DIR}/deploy/techdesk.service" /etc/systemd/system/techdesk.service
systemctl daemon-reload
systemctl enable techdesk.service
systemctl restart techdesk.service

echo "==> Done. Check status with: systemctl status techdesk"
echo "    Logs:    journalctl -u techdesk -f"
echo "    Health:  curl -s http://127.0.0.1:8080/api/health"
