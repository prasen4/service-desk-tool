#!/usr/bin/env bash
#
# Deploy or update the Tech Desk app on an EC2 instance using Docker Compose,
# as an alternative to the native systemd path (deploy.sh). Run from a
# checkout of the repository on the instance:
#
#   sudo bash deploy/deploy-docker.sh
#
# It is safe to re-run: `git pull` first, then re-run this script to rebuild
# and restart the container with the new code.
#
# Prerequisite: Docker Engine + the Compose plugin must already be installed
# (see DEPLOYMENT.md for install snippets on Ubuntu / Amazon Linux 2023).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not installed. See DEPLOYMENT.md for install steps." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: the 'docker compose' plugin is not installed." >&2
    exit 1
fi

if [ ! -f .env ]; then
    echo "==> Seeding .env from example (EDIT THIS with your real API key + settings)"
    cp .env.example .env
    sed -i "s#^ENV=.*#ENV=production#" .env
    echo "    -> Edit ./.env now (OPENAI_API_KEY, LLM_PROVIDER, CORS_ORIGINS), then re-run this script."
    exit 0
fi

echo "==> Building and starting the stack"
docker compose up -d --build

echo "==> Waiting for the app to become healthy"
for _ in $(seq 1 30); do
    if curl -fs http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
        echo "==> Healthy."
        curl -s http://127.0.0.1:8080/api/health
        echo
        exit 0
    fi
    sleep 2
done

echo "WARNING: /api/health did not respond after 60s — check logs:" >&2
echo "    docker compose logs -f" >&2
exit 1
