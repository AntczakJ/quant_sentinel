# Deployment Guide

End-to-end deployment of Quant Sentinel (API + Telegram bot + frontend)
on a Linux VPS. Includes systemd services, nginx reverse proxy, SSL,
and operational procedures.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  VPS (Ubuntu 22.04+ or Debian 12+)                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ nginx    │──│ FastAPI  │──│ data/sentinel.db  │  │
│  │ :443 SSL │  │ :8000    │  │ (SQLite + WAL)    │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
│                     │                    │          │
│                     └────────┬───────────┘          │
│                              │                      │
│                      ┌──────────────┐               │
│                      │ Telegram bot │               │
│                      │ (long poll)  │               │
│                      └──────────────┘               │
│                                                     │
│  Background tasks (in API process):                 │
│    - Scanner (5 min cadence)                        │
│    - Resolver (5 min)                               │
│    - Prices broadcaster (5s SSE)                    │
│    - Health monitor (10 min → Telegram alerts)      │
│    - Retention cleanup (24h)                        │
└─────────────────────────────────────────────────────┘
         │
         └── optional: Turso cloud sync
```

## Minimum VPS specs

- **2 vCPU** (ML ensemble needs headroom)
- **4 GB RAM** (TensorFlow + Python runtime)
- **20 GB SSD** (DB grows ~100MB/month, logs rotated)
- **Ubuntu 22.04 / Debian 12** (tested), others should work

**Tested providers:** Hetzner CX22 (€4.50/mo), OVHcloud VPS Value.

## Initial setup

### 1. System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.13 python3.13-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    git build-essential sqlite3 \
    curl htop ufw
```

### 2. Create deploy user (security)

```bash
sudo useradd -m -s /bin/bash -G www-data quant
sudo mkdir -p /opt/quant_sentinel
sudo chown quant:quant /opt/quant_sentinel
sudo su - quant
```

### 3. Clone + setup

```bash
cd /opt/quant_sentinel
git clone https://github.com/AntczakJ/quant_sentinel.git .

python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Frontend build (if not pre-built)
cd frontend
npm ci
npm run build
cd ..
```

### 4. Environment configuration

```bash
cp .env.example .env
nano .env  # set all API keys (see below)
chmod 600 .env  # only owner can read
```

Required variables:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
OPENAI_API_KEY=...
TWELVE_DATA_API_KEY=...
FINNHUB_API_KEY=...
FRED_API_KEY=...           # optional (macro)
JWT_SECRET=<64 random chars>
DATABASE_URL=data/sentinel.db
```

Optional:
```
TURSO_URL=libsql://...      # cloud backup
TURSO_TOKEN=...
```

### 5. Initialize database

```bash
source .venv/bin/activate
python -c "from src.core.database import NewsDB; NewsDB()"
# Creates data/sentinel.db with schema + initial indexes
```

### 6. Verify install

```bash
python verify_install.py --skip-api
# Should show 5/5 offline checks passed
```

## systemd services

### API service

Create `/etc/systemd/system/quant-sentinel-api.service`:

```ini
[Unit]
Description=Quant Sentinel API
After=network.target
Wants=network.target

[Service]
Type=simple
User=quant
Group=quant
WorkingDirectory=/opt/quant_sentinel
Environment="PATH=/opt/quant_sentinel/.venv/bin:/usr/bin"
EnvironmentFile=/opt/quant_sentinel/.env
ExecStart=/opt/quant_sentinel/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/quant_sentinel/api.log
StandardError=append:/var/log/quant_sentinel/api.err.log

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/quant_sentinel/data /opt/quant_sentinel/logs /opt/quant_sentinel/models /var/log/quant_sentinel

[Install]
WantedBy=multi-user.target
```

### Telegram bot service

Create `/etc/systemd/system/quant-sentinel-bot.service`:

```ini
[Unit]
Description=Quant Sentinel Telegram Bot
After=network.target quant-sentinel-api.service

[Service]
Type=simple
User=quant
Group=quant
WorkingDirectory=/opt/quant_sentinel
Environment="PATH=/opt/quant_sentinel/.venv/bin:/usr/bin"
EnvironmentFile=/opt/quant_sentinel/.env
ExecStart=/opt/quant_sentinel/.venv/bin/python -m src.main
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/quant_sentinel/bot.log
StandardError=append:/var/log/quant_sentinel/bot.err.log

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Enable + start

```bash
sudo mkdir -p /var/log/quant_sentinel
sudo chown quant:quant /var/log/quant_sentinel

sudo systemctl daemon-reload
sudo systemctl enable quant-sentinel-api quant-sentinel-bot
sudo systemctl start quant-sentinel-api quant-sentinel-bot

# Check status
sudo systemctl status quant-sentinel-api
sudo journalctl -u quant-sentinel-api -f
```

## nginx + SSL

Create `/etc/nginx/sites-available/quant-sentinel`:

```nginx
server {
    listen 80;
    server_name quant-sentinel.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name quant-sentinel.example.com;

    ssl_certificate /etc/letsencrypt/live/quant-sentinel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/quant-sentinel.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    client_max_body_size 10M;

    # Frontend SPA (built files)
    root /opt/quant_sentinel/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE for live prices (no buffering)
    location /api/sse/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 24h;
    }

    # WebSocket upgrade
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    # Static assets cache
    location ~* \.(js|css|woff2|png|svg|jpg|ico)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

Enable + get SSL:

```bash
sudo ln -s /etc/nginx/sites-available/quant-sentinel /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

sudo certbot --nginx -d quant-sentinel.example.com
# Follow prompts; certbot auto-modifies nginx config + sets auto-renew
```

## Firewall (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

## Post-deploy verification

```bash
# From external machine:
curl https://quant-sentinel.example.com/api/health
# {"status":"healthy","uptime_seconds":...}

curl https://quant-sentinel.example.com/api/health/scanner
# {"status":"no_data"|"healthy",...}

# SSH to server + run full verify:
ssh quant@vps
cd /opt/quant_sentinel
source .venv/bin/activate
python verify_install.py --api https://quant-sentinel.example.com
# Should show 8/8 checks passed
```

## Updating (git pull + restart)

```bash
ssh quant@vps
cd /opt/quant_sentinel
git pull origin main

# Python deps (if requirements.txt changed)
source .venv/bin/activate
pip install -r requirements.txt

# Frontend rebuild (if frontend/ changed)
cd frontend && npm ci && npm run build && cd ..

# Database migrations (future — alembic)
# alembic upgrade head

# Restart services
sudo systemctl restart quant-sentinel-api quant-sentinel-bot
sudo systemctl status quant-sentinel-api

# Verify
python verify_install.py --api https://quant-sentinel.example.com
```

**Expected downtime:** ~15s (systemctl restart). Scanner/bot pick up changes
automatically. No user action needed unless JWT_SECRET rotated.

## Backup strategy

### Automated daily backup

Add to `crontab -e` as `quant` user:

```cron
# Daily DB backup at 02:00, keep 14 days
0 2 * * * cd /opt/quant_sentinel && .venv/bin/python -c "from src.ops.db_backup import create_backup; create_backup('daily')"

# Retention: prune backups >14 days
0 3 * * * find /opt/quant_sentinel/data/backups/ -name "sentinel_*.db" -mtime +14 -delete
```

### Offsite backup (recommended)

```bash
# Daily rclone sync to cloud
0 4 * * * rclone sync /opt/quant_sentinel/data/backups/ remote:quant-sentinel-backups/
```

### Restore drill (test monthly)

```bash
cd /tmp
cp /opt/quant_sentinel/data/backups/sentinel_20260412_020000.db ./restore_test.db
sqlite3 restore_test.db "SELECT COUNT(*) FROM trades;"  # should return expected count
sqlite3 restore_test.db "PRAGMA integrity_check;"  # should return "ok"
rm restore_test.db
```

## Monitoring + alerting

- Health monitor (`src/ops/health_monitor.py`) runs in API process,
  sends Telegram alerts on issues every 10 min.
- Log rotation via `logging.RotatingFileHandler` (5MB × 5).
- systemd `Restart=on-failure` auto-recovers from crashes.
- Optional: external uptime monitor (UptimeRobot, Pingdom) pinging
  `/api/health` every 5 min.

## Disaster recovery

### VPS dies

1. Spin up new VPS with same OS.
2. Follow "Initial setup" above.
3. Restore latest backup:
   ```bash
   cp /path/to/backup/sentinel_latest.db /opt/quant_sentinel/data/sentinel.db
   chown quant:quant /opt/quant_sentinel/data/sentinel.db
   sudo systemctl start quant-sentinel-api quant-sentinel-bot
   ```
4. Update DNS to new IP.
5. Run `verify_install.py --api https://...`

**RTO (Recovery Time Objective):** ~2 hours if VPS + backup available.

### Database corruption

```bash
sudo systemctl stop quant-sentinel-api quant-sentinel-bot
cd /opt/quant_sentinel
sqlite3 data/sentinel.db "PRAGMA integrity_check;"  # identify damage
# If bad:
mv data/sentinel.db data/sentinel.db.corrupted
cp data/backups/sentinel_<latest>.db data/sentinel.db
sudo systemctl start quant-sentinel-api quant-sentinel-bot
```

## Troubleshooting

**API won't start**
- `sudo journalctl -u quant-sentinel-api -n 50` for errors
- Common: missing env var → check `.env` + `EnvironmentFile=` path
- Python import errors → re-run `pip install -r requirements.txt`

**Scanner not running / stale**
- Check `/api/health/scanner` — should show recent run
- `logs/sentinel.log` for scan cycle output
- Rate limiter: if data_fetch_failures high, Twelve Data quota exhausted

**High memory usage**
- TensorFlow + 6 ML models ≈ 2-3 GB baseline
- If OOM: upgrade to 8GB VPS or set `TF_CPP_MIN_LOG_LEVEL=3` + force CPU mode
