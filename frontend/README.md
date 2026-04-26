# Quant Sentinel — Frontend v3

Rebuilt from scratch on 2026-04-26. Inspired by Revolut (financial gradients,
clear data hierarchy), Apple (typography, generous whitespace, premium feel),
and outfit.hellohello.is (bold confidence, asymmetric grids).

Previous frontend preserved at `../frontend_v1/`.

## Stack

- **React 18 + TypeScript** — strict mode, modern hooks
- **Vite** — fast dev server, native ESM
- **Tailwind CSS** — utility-first design system
- **@tanstack/react-query** — data fetching with stale-while-revalidate
- **Framer Motion** — page transitions, layout animations
- **lightweight-charts** — TradingView-grade candles
- **react-router-dom v6** — client-side routing

## Design tokens (in tailwind.config.js)

- **Colors:** `ink-{0..900}` (true black to white), `gold-{400..600}` (premium accent),
  `bull` / `bear` / `neutral` / `info` (signal colors)
- **Typography:** `display-xl` (96px) → `micro` (11px) — Apple-inspired scale
- **Surfaces:** `.surface`, `.surface-raised`, `.surface-interactive`
- **Pills:** `.pill`, `.pill-bull`, `.pill-bear`, `.pill-gold`
- **Numbers:** `.num` (mono + tabular for tables)

Dark theme is primary. Light mode is unimplemented — flip happens via `.light` class
on `<html>` if needed later.

## Pages

- `/` — Dashboard (hero with live spot price + account, key stats, recent signals,
  scanner panel, macro strip)
- `/chart` — Candles for XAU/USD across 5m/15m/1h/4h
- `/trades` — All trades with filter chips (all/win/loss/open/long/short)
- `/models` — V2 ensemble voters with hold-out scores
- `/settings` — API state, account state, summary of tonight's changes

## Dev

```bash
cd frontend
npm install
npm run dev    # opens http://127.0.0.1:5173
```

Vite proxies `/api/*` → `http://127.0.0.1:8000/api/*` so no CORS or
`VITE_API_URL` env is required during dev.

## Build

```bash
npm run build  # type-check + build → dist/
npm run preview  # serve dist locally
```

## Aesthetic notes

- **Dark first.** Quant tools live on dark. The page background is `#0a0a0c` with
  subtle radial gold + blue meshes for depth. This is the Revolut / Apple intersection.
- **Typography drives hierarchy.** Display sizes go up to 96px; we use them sparingly
  on the dashboard hero. Body text is 15px for legibility on 1080p+ monitors.
- **Numbers use tabular figures.** The `.num` utility applies `font-mono` +
  `tabular-nums` so ticker prices and P&L don't shift width as digits change.
- **Motion is purposeful, not decorative.** Cards fade-up on mount; nav has a
  shared `layoutId` so the active-pill slides between routes. Hover states are
  subtle (border tightening + 0.5px lift) — no garish shadows or color shifts.
- **Surfaces are layered.** Glass-like `.surface` (translucent), solid `.surface-raised`
  (elevated card), `.surface-interactive` (hover-aware). Avoids the flat
  "everything is one card" feel.

## What's intentionally simple (room to grow)

- No state management lib beyond react-query — the trading store from v1 was
  large; current data flow is: react-query → component. Add Zustand later
  if a store is needed.
- No i18n — v1 had Polish + English; v3 ships English-only until justified.
- No virtualized tables — Trades shows 200 rows max (fine for current sample).
  Switch to react-virtual if sample exceeds ~5k.
- No auth UI — API has `API_SECRET_KEY` but local dev uses 127.0.0.1 only.
- No ws/SSE wiring — react-query polls (5-30s). Real-time tick updates would
  need an SSE listener layered into the relevant queries.

## v1 was preserved

`frontend_v1/` is the React 18 + react-grid-layout dashboard with ~50 components.
It still builds. To switch back temporarily: rename `frontend/ ↔ frontend_v1/`.
