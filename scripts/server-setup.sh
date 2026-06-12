#!/usr/bin/env bash
# server-setup.sh — One-time bootstrap for a fresh Hetzner Ubuntu 24.04 server.
# Run via: make deploy-first  (which SSHes in and pipes this script)
# Do NOT run more than once; subsequent deploys use: make deploy
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/zdenovo}"
REPO_URL="${REPO_URL:-}"

echo "==> [1/5] System update..."
apt-get update -qq
apt-get upgrade -y -qq

echo "==> [2/5] Installing dependencies..."
apt-get install -y -qq \
  git \
  make \
  curl \
  ca-certificates \
  ufw

echo "==> [3/5] Installing Docker Engine + Compose plugin..."
curl -fsSL https://get.docker.com | sh
apt-get install -y -qq docker-compose-plugin

echo "==> [4/5] Configuring firewall (UFW)..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "Firewall status:"
ufw status verbose

echo "==> [5/5] Cloning repository..."
if [ -z "$REPO_URL" ]; then
  echo "ERROR: REPO_URL is not set. Set it in .env and re-run." >&2
  exit 1
fi

mkdir -p "$(dirname "$DEPLOY_DIR")"
if [ -d "$DEPLOY_DIR/.git" ]; then
  echo "Repo already cloned at $DEPLOY_DIR — skipping clone."
else
  git clone "$REPO_URL" "$DEPLOY_DIR"
fi

echo ""
echo "✓ Server setup complete."
echo ""
echo "Next steps (handled automatically by 'make deploy-first'):"
echo "  1. Copy .env to $DEPLOY_DIR/.env"
echo "  2. Run: cd $DEPLOY_DIR && make cert-init"
echo "  3. Run: cd $DEPLOY_DIR && make prod"
