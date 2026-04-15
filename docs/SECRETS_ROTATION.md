# Secrets Rotation Guide

Procedures for rotating API keys and tokens without downtime.

## Overview

| Secret | Variable | Rotation impact | Recommended frequency |
|---|---|---|---|
| Telegram Bot Token | `TELEGRAM_BOT_TOKEN` | Bot offline ~30s | On breach only |
| Twelve Data API | `TWELVE_DATA_API_KEY` | Scanner uses mock fallback | Every 90 days |
| OpenAI API | `OPENAI_API_KEY` | `/agent` endpoint fails | Every 90 days |
| FRED API | `FRED_API_KEY` | Macro = neutral, trading OK | Yearly |
| Finnhub API | `FINNHUB_API_KEY` | News sentiment = neutral | Every 90 days |
| Turso Auth | `TURSO_URL` / `TURSO_TOKEN` | Cloud sync halts, local OK | Every 90 days |
| JWT Secret | `JWT_SECRET` | All users logged out | On breach only |

## Twelve Data API key rotation

**Pre-requisites:** admin access to Twelve Data dashboard, SSH to VPS.

```bash
# 1. Generate new key at https://twelvedata.com/account/api-keys
#    Set same rate limit (55 credits/min Basic) or upgrade plan.

# 2. SSH to server
ssh user@quant-sentinel-vps

# 3. Edit .env (VPS has read-only git checkout — don't commit)
nano /opt/quant_sentinel/.env
# TWELVE_DATA_API_KEY=<old>  →  <new>

# 4. Restart API (scanner will pick up new key on next cycle)
systemctl restart quant-sentinel-api

# 5. Verify new key is working
curl https://quant-sentinel.example.com/api/metrics | jq .scanner_health
# data_fetch_failures should NOT be increasing rapidly

# 6. Revoke old key in Twelve Data dashboard (24h grace period)
```

**Expected downtime:** ~30s (API restart). Scanner cycle during restart falls
back to mock data — no trades placed in that window.

## Telegram Bot Token rotation

**Critical:** new token = new bot object. Users may need to re-enable notifications.

```bash
# 1. Talk to @BotFather on Telegram:
#    /revoke  → confirm for current bot
#    /token   → BotFather generates new token
#               Copy it immediately — no UI to retrieve later.

# 2. Update .env
nano .env
# TELEGRAM_BOT_TOKEN=<new>

# 3. Restart bot
systemctl restart quant-sentinel-bot

# 4. Announce to users: bot may require /start re-subscription.
```

## JWT Secret rotation (security incident response)

**Effect:** all active JWT tokens invalidated immediately. All users must re-login.

```bash
# 1. Generate new secret (64 chars random)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 2. Update .env
nano .env
# JWT_SECRET=<new>

# 3. Restart API (atomic — no graceful rotation possible)
systemctl restart quant-sentinel-api

# 4. Notify users to re-login.
```

## Emergency: suspected breach

```bash
# 1. Revoke ALL external secrets immediately:
#    - Twelve Data dashboard → Delete key
#    - BotFather → /revoke
#    - OpenAI dashboard → Delete key
#    - Finnhub dashboard → Delete key
#    - Turso dashboard → Delete auth token

# 2. Force halt trading (in-process kill switch):
python -c "from src.trading.risk_manager import get_risk_manager; get_risk_manager().halt('security incident')"

# 3. Rotate JWT secret (logs out all users)

# 4. Audit logs for suspicious activity:
grep -i "suspicious\|error\|auth" logs/sentinel.log | tail -100
grep -c "ERROR" logs/sentinel.log  # error count

# 5. Check recent trades for anomalies:
sqlite3 data/sentinel.db "SELECT * FROM trades ORDER BY id DESC LIMIT 50;"

# 6. Restart all services with new credentials.
```

## Automation recommendations (future)

- **HashiCorp Vault** integration for secret storage.
- **GitHub Actions** with encrypted secrets for deploy.
- **Automated rotation** via scheduler (monthly) for long-lived keys.
- **Grace period support** in code: accept both old and new key for 24h
  during rotation, eliminating downtime completely.

## What NEVER to do

- **Never commit `.env`** — already in `.gitignore`. Verify:
  ```bash
  git check-ignore .env  # should print ".env"
  ```
- **Never log secret values** — `logger.info(f"Token: {TOKEN}")` is a breach.
- **Never send secrets via email/chat** — use `gpg --encrypt` or password
  managers.
- **Never reuse secrets** between staging and production.
