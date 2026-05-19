#!/bin/bash
# SignalPay VPS deployment script
# Run as: bash vps-setup.sh
# Assumes: Ubuntu, running as laolex, repo at ~/signalpay

set -euo pipefail

REPO_DIR="$HOME/signalpay"
SERVICE_NAME="signalpay-backend"
PORT=8001  # use 8001 to avoid conflict with trading-agents on 8000

echo "=== SignalPay VPS Deploy ==="

# ── 1. Clone or pull ────────────────────────────────────────────
if [ -d "$REPO_DIR/.git" ]; then
  echo "[1/6] Pulling latest..."
  git -C "$REPO_DIR" pull --ff-only
else
  echo "[1/6] Cloning repo..."
  git clone https://github.com/Laolex/signalpay.git "$REPO_DIR"
fi

# ── 2. Python venv ──────────────────────────────────────────────
echo "[2/6] Setting up Python venv..."
cd "$REPO_DIR"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r backend/requirements.txt
echo "    deps installed"

# ── 3. Env file ─────────────────────────────────────────────────
echo "[3/6] Checking .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
  echo "    ERROR: .env not found — copy it to $REPO_DIR/.env before proceeding"
  exit 1
fi
echo "    .env present"

# ── 4. Frontend build ───────────────────────────────────────────
echo "[4/6] Building frontend..."
cd "$REPO_DIR/frontend"
npm install --silent
VITE_API_BASE="" npm run build
echo "    frontend built to dist/"

# ── 5. systemd service ──────────────────────────────────────────
echo "[5/6] Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=SignalPay Backend (FastAPI x402 Signal Provider)
After=network.target

[Service]
Type=simple
User=laolex
WorkingDirectory=${REPO_DIR}
EnvironmentFile=${REPO_DIR}/.env
Environment=PYTHONPATH=${REPO_DIR}/backend
Environment=PORT=${PORT}
Environment=CORS_ALLOW_ORIGINS=https://signalpay.laolex.com,http://localhost:5173
ExecStart=${REPO_DIR}/.venv/bin/uvicorn app.server:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}
sleep 2
sudo systemctl is-active --quiet ${SERVICE_NAME} && echo "    service running" || (echo "    service FAILED"; sudo journalctl -u ${SERVICE_NAME} -n 20; exit 1)

# ── 6. Nginx config ─────────────────────────────────────────────
echo "[6/6] Configuring nginx..."
sudo tee /etc/nginx/sites-available/signalpay > /dev/null <<'EOF'
server {
    listen 80;
    server_name signalpay.laolex.com _;

    # Frontend static files
    root /home/laolex/signalpay/frontend/dist;
    index index.html;

    # Backend API proxy
    location ~ ^/(signals|discovery|stats|feed|agent|health)/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # SSE support for /agent/run
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/signalpay /etc/nginx/sites-enabled/signalpay
sudo nginx -t && sudo systemctl reload nginx
echo "    nginx configured"

echo ""
echo "=== Deploy complete ==="
echo "  Backend: http://$(hostname -I | awk '{print $1}'):${PORT}"
echo "  Health:  curl http://localhost:${PORT}/"
echo "  Logs:    journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "Next: point DNS for signalpay.laolex.com → $(hostname -I | awk '{print $1}')"
echo "Then: certbot --nginx -d signalpay.laolex.com"
