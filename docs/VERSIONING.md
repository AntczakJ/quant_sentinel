# Versioning Policy

Semantic Versioning (https://semver.org): **MAJOR.MINOR.PATCH**.

Current version: **3.0.0** (see `pyproject.toml`).

## Version bump rules

| Change type | Bump | Example |
|---|---|---|
| Breaking API change (removed endpoint, renamed JSON field, DB schema destructive) | MAJOR | 3.x → 4.0.0 |
| New feature, new endpoint, new scanner logic (backward-compatible) | MINOR | 3.0 → 3.1.0 |
| Bug fix, doc update, performance improvement | PATCH | 3.0.0 → 3.0.1 |
| Security patch | PATCH | Always bumped |

## Release process

```bash
# 1. Update version in pyproject.toml
nano pyproject.toml  # version = "3.1.0"

# 2. Update CHANGELOG.md — move [Unreleased] items to [3.1.0] - YYYY-MM-DD
nano CHANGELOG.md

# 3. Commit version bump
git add pyproject.toml CHANGELOG.md
git commit -m "release: v3.1.0"

# 4. Tag
git tag -a v3.1.0 -m "Release 3.1.0: <one-line summary>"

# 5. Push with tags
git push origin main
git push origin v3.1.0

# 6. Create GitHub release
gh release create v3.1.0 --title "v3.1.0" --notes-file <(sed -n '/## \[3.1.0\]/,/## \[/p' CHANGELOG.md | head -n -1)
```

## Pending release

Based on CHANGELOG.md [Unreleased] section, next tag should be:

- **v3.1.0** — huge feature release (backtest infrastructure P0-P8, RL
  overhaul with vol_normalize fix, observability/defense/tools phases,
  dashboard integration)

This is ≥10 MINOR-bumpable changes. Not PATCH.

## Version in deployed artifacts

- Backend `/api/health`: includes uptime but NOT version. TODO: add
  `version` field reading from `pyproject.toml`.
- Frontend `package.json` version: "2.1.0" (out of sync with backend —
  independent tracking is intentional).
- Docker image: not tagged with version yet. TODO: CI builds `quant-sentinel:3.1.0`.

## Legacy tags

- `v1.0-pre-rework` (2026 early) — before FastAPI migration.
- No `v2.x` tags (2.0 and 2.1 were unreleased dev states).
- Current 3.0.0 = post-FastAPI + RL ensemble + Phase 1-4 complete.
