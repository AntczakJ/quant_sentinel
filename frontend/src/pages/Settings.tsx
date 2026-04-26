import { useQuery } from '@tanstack/react-query'
import NumberFlow from '@number-flow/react'
import { api } from '@/api/client'
import { Card } from '@/components/Card'
import { AuroraBackground } from '@/components/AuroraBackground'
import { useEffect, useState } from 'react'
import { isSoundEnabled, setSoundEnabled } from '@/lib/sound'

export default function Settings() {
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health })
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })

  const [soundOn, setSoundOn] = useState(false)
  useEffect(() => setSoundOn(isSoundEnabled()), [])

  return (
    <div className="relative flex flex-col gap-8 overflow-visible">
      <div className="absolute inset-0 -z-10 overflow-hidden pointer-events-none rounded-xl3">
        <AuroraBackground intensity={0.55} />
      </div>

      <header className="reveal-on-scroll">
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">Settings</h1>
        <p className="text-body text-ink-600 mt-2">System configuration and live state.</p>
      </header>

      <div className="grid lg:grid-cols-2 gap-4 reveal-on-scroll">
        <Card variant="raised" className="p-6">
          <h3 className="text-title font-display">API</h3>
          <div className="mt-4 space-y-2">
            {[
              ['Status', health?.status ?? '—'],
              ['Uptime', health?.uptime ?? '—'],
              ['Models loaded', String(health?.models_loaded ?? '—')],
            ].map(([k, v]) => (
              <Row key={k as string} label={k as string} value={v as string} />
            ))}
          </div>
        </Card>

        <Card variant="raised" className="p-6">
          <h3 className="text-title font-display">Account</h3>
          <div className="mt-4 space-y-2">
            <Row
              label="Balance"
              value={
                portfolio?.balance != null
                  ? `${portfolio.balance.toFixed(2)} ${portfolio.currency || ''}`
                  : '—'
              }
            />
            <Row
              label="P&L"
              value={
                portfolio?.pnl != null
                  ? `${portfolio.pnl >= 0 ? '+' : ''}${portfolio.pnl.toFixed(2)}`
                  : '—'
              }
            />
            <Row
              label="P&L %"
              value={
                portfolio?.pnl_pct != null
                  ? `${portfolio.pnl_pct >= 0 ? '+' : ''}${portfolio.pnl_pct.toFixed(2)}%`
                  : '—'
              }
            />
            <Row label="Open positions" value={String(portfolio?.open_positions ?? 0)} />
          </div>
        </Card>

        {/* ─── Audio toggle ──────────────────────────────────────── */}
        <Card variant="raised" className="p-6">
          <h3 className="text-title font-display">Audio feedback</h3>
          <p className="text-caption text-ink-600 mt-1">
            Subtle synth tones on trade events and Cmd+K actions. Off by default.
          </p>
          <div className="mt-4 flex items-center justify-between">
            <span className="text-body text-ink-800">
              {soundOn ? 'Enabled' : 'Disabled'}
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={soundOn}
              onClick={() => {
                const next = !soundOn
                setSoundEnabled(next)
                setSoundOn(next)
              }}
              className={`relative w-11 h-6 rounded-full border transition-all ${
                soundOn
                  ? 'bg-gold-500/30 border-gold-500/50 shadow-glow-gold'
                  : 'bg-white/[0.04] border-white/10'
              }`}
            >
              <span
                className={`absolute top-0.5 w-5 h-5 rounded-full transition-all ${
                  soundOn ? 'left-5 bg-gold-400' : 'left-0.5 bg-ink-600'
                }`}
              />
            </button>
          </div>
        </Card>

        {/* ─── Rate limit (API credits) ──────────────────────── */}
        <Card variant="raised" className="p-6">
          <RateLimitBlock />
        </Card>

        {/* ─── Database stats ───────────────────────────────── */}
        <Card variant="raised" className="p-6">
          <DbStatsBlock />
        </Card>

        {/* ─── System diagnostic ─────────────────────────────── */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <SystemInfoBlock />
        </Card>

        {/* ─── Tonight's session changes ───────────────────────── */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <h3 className="text-title font-display">Tonight's session changes (2026-04-26)</h3>
          <p className="text-caption text-ink-600 mt-1 mb-4">
            See <span className="font-mono">memory/session_2026-04-26_summary.md</span> for full detail.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {[
              ['B1 LONG penalty', '−15 → −7', 'softened (asymmetry flipped)'],
              ['B4 asian LONG', '−25 → −10', 'softened'],
              ['B7 SHORT in zielony', '−20', 'new (inverse-B1)'],
              ['Per-grade risk_percent×', '1.5 / 0.7', 'removed'],
              ['DISABLE_TRAILING', '.env flag', 'available, opt-in'],
              ['MAX_LOT_CAP', '0.01', '.env enforced'],
              ['Streak threshold', '5 → 8', 'tolerance for normal variance'],
              ['Best backtest', 'PF 1.80', 'equal_lot_combo, 30d'],
            ].map(([k, v, note]) => (
              <div
                key={k as string}
                className="surface p-4 rounded-xl flex items-start justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="text-caption text-ink-700 truncate">{k}</div>
                  <div className="text-micro text-ink-600">{note}</div>
                </div>
                <div className="num text-body shrink-0 font-display">{v}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/[0.04] last:border-0">
      <span className="text-caption text-ink-600">{label}</span>
      <span className="num text-body">{value}</span>
    </div>
  )
}

// ─── Database stats — sentinel.db counts + size ───────────────────────
function DbStatsBlock() {
  const { data, isError } = useQuery({
    queryKey: ['db-stats'],
    queryFn: api.dbStats,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
  if (isError) {
    return (
      <div>
        <h3 className="text-title font-display">Database</h3>
        <p className="text-caption text-bear mt-2">/api/system/db-stats failed.</p>
      </div>
    )
  }
  if (!data) {
    return (
      <div>
        <h3 className="text-title font-display">Database</h3>
        <p className="text-caption text-ink-600 mt-2">Loading…</p>
      </div>
    )
  }
  const t = data.trades
  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-title font-display">Database</h3>
          <p className="text-caption text-ink-600 mt-1">
            {data.file.path}
            {data.file.size_kb != null && (
              <> · {(data.file.size_kb / 1024).toFixed(1)} MB</>
            )}
          </p>
        </div>
        <div className="text-right">
          <div className="text-micro uppercase tracking-wider text-ink-600">Trades · WR</div>
          <div className="num text-headline font-display">
            <NumberFlow value={t.total} format={{ maximumFractionDigits: 0 }} respectMotionPreference />
            {t.win_rate_pct != null && (
              <span className={`text-caption ml-2 ${t.win_rate_pct >= 50 ? 'text-bull' : 'text-bear'}`}>
                {t.win_rate_pct.toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-caption">
        <Row label="Trades · open"   value={String(t.open)} />
        <Row label="Trades · wins"   value={String(t.wins)} />
        <Row label="Trades · closed" value={String(t.closed)} />
        <Row label="Trades · losses" value={String(t.losses)} />
        <Row label="Rejected setups" value={String(data.tables.rejected_setups ?? '—')} />
        <Row label="Scanner signals" value={String(data.tables.scanner_signals ?? '—')} />
        <Row label="ML predictions"  value={String(data.tables.ml_predictions  ?? '—')} />
        <Row label="Dynamic params"  value={String(data.tables.dynamic_params  ?? '—')} />
        <Row label="Pattern stats"   value={String(data.tables.pattern_stats   ?? '—')} />
        <Row label="Model alerts"    value={String(data.tables.model_alerts    ?? '—')} />
      </div>
    </div>
  )
}

// ─── Rate limit — TwelveData credit bucket ─────────────────────────────
function RateLimitBlock() {
  const { data, isError } = useQuery({
    queryKey: ['rate-limit'],
    queryFn: api.rateLimit,
    refetchInterval: 10_000,
    staleTime: 5_000,
  })
  if (isError) {
    return (
      <div>
        <h3 className="text-title font-display">API credits</h3>
        <p className="text-caption text-bear mt-2">/api/system/rate-limit failed.</p>
      </div>
    )
  }
  if (!data) {
    return (
      <div>
        <h3 className="text-title font-display">API credits</h3>
        <p className="text-caption text-ink-600 mt-2">Loading…</p>
      </div>
    )
  }

  const pct = data.max_limit > 0 ? (data.current_credits / data.max_limit) * 100 : 0
  const safePct = data.max_limit > 0 ? (data.safe_limit / data.max_limit) * 100 : 100
  const tone = pct < 20 ? 'bear' : pct < 50 ? 'gold' : 'bull'
  const toneClass = tone === 'bear' ? 'text-bear' : tone === 'gold' ? 'text-gold-400' : 'text-bull'
  const fillBg = tone === 'bear' ? 'bg-bear/60' : tone === 'gold' ? 'bg-gold-500/60' : 'bg-bull/60'

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-title font-display">API credits</h3>
          <p className="text-caption text-ink-600 mt-1">
            TwelveData primary bucket · refilled {Math.max(0, Math.round((Date.now() / 1000) - data.last_refill))} s ago
          </p>
        </div>
        <div className="text-right">
          <div className="text-micro uppercase tracking-wider text-ink-600">Now</div>
          <div className={`num text-headline font-display ${toneClass}`}>
            <NumberFlow
              value={data.current_credits}
              format={{ maximumFractionDigits: 0 }}
              respectMotionPreference
            />
            <span className="text-caption text-ink-600"> / {data.max_limit}</span>
          </div>
        </div>
      </div>

      {/* Bucket bar */}
      <div className="mt-4 relative h-2 rounded-full bg-white/[0.04] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${fillBg}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
        {/* Safe-limit dashed marker */}
        <div
          className="absolute top-0 bottom-0 w-px bg-white/30"
          style={{ left: `${Math.min(100, safePct)}%` }}
          title={`safe limit: ${data.safe_limit}`}
        />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-4 text-caption">
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">Used / min</div>
          <div className="num text-body mt-0.5">
            <NumberFlow value={data.credits_used_last_min} format={{ maximumFractionDigits: 0 }} respectMotionPreference />
          </div>
        </div>
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">Recent reqs</div>
          <div className="num text-body mt-0.5">
            <NumberFlow value={data.recent_requests} format={{ maximumFractionDigits: 0 }} respectMotionPreference />
          </div>
        </div>
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">All-time</div>
          <div className="num text-body mt-0.5">
            <NumberFlow value={data.all_requests_count} format={{ maximumFractionDigits: 0 }} respectMotionPreference />
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── System info — versions, models, GPU, disk, env ───────────────────
function SystemInfoBlock() {
  const { data, isError } = useQuery({
    queryKey: ['system-info'],
    queryFn: api.systemInfo,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  if (isError) {
    return (
      <div>
        <h3 className="text-title font-display">System diagnostic</h3>
        <p className="text-caption text-bear mt-2">Failed to load /api/system/info.</p>
      </div>
    )
  }
  if (!data) {
    return (
      <div>
        <h3 className="text-title font-display">System diagnostic</h3>
        <p className="text-caption text-ink-600 mt-2">Loading…</p>
      </div>
    )
  }

  const v = data.versions
  const versionRows: Array<[string, string | null]> = [
    ['Python', data.platform.python],
    ['FastAPI', v.fastapi],
    ['Pydantic', v.pydantic],
    ['NumPy', v.numpy],
    ['Pandas', v.pandas],
    ['Polars', v.polars],
    ['Numba', v.numba],
    ['XGBoost', v.xgboost],
    ['Treelite', v.treelite],
    ['DuckDB', v.duckdb],
    ['Torch', v.torch],
    ['TensorFlow', v.tensorflow],
    ['Logfire', v.logfire],
    ['Sentry', v.sentry_sdk],
  ]

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-title font-display">System diagnostic</h3>
          <p className="text-caption text-ink-600 mt-1">
            {data.platform.system} {data.platform.release} {data.platform.machine}
            {' · '}
            <span className={data.xgb_loader.status === 'loaded' ? 'text-bull' : 'text-ink-700'}>
              XGB voter: {data.xgb_loader.path ?? data.xgb_loader.status}
            </span>
            {data.git?.sha && (
              <>
                {' · '}
                <span className="font-mono text-ink-700">
                  {data.git.branch}@{data.git.sha}
                  {data.git.dirty && <span className="text-gold-400" title="working tree dirty"> ●</span>}
                </span>
              </>
            )}
          </p>
        </div>
        <div className="text-right">
          <div className="text-micro uppercase tracking-wider text-ink-600">Memory</div>
          <div className="num text-headline font-display">
            {data.process.rss_mb != null ? (
              <NumberFlow value={data.process.rss_mb} format={{ maximumFractionDigits: 0 }} suffix=" MB" respectMotionPreference />
            ) : (
              '—'
            )}
          </div>
          <div className="text-micro text-ink-600">
            {data.process.num_threads ?? '—'} threads · {data.process.uptime_s != null ? Math.round(data.process.uptime_s / 60) : '—'} min uptime
          </div>
        </div>
      </div>

      {/* Versions grid */}
      <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
        {versionRows.map(([k, val]) => (
          <div key={k} className="surface p-3 rounded-xl">
            <div className="text-micro uppercase tracking-wider text-ink-600">{k}</div>
            <div className={`num text-caption mt-0.5 ${val ? 'text-ink-900' : 'text-ink-600'}`}>
              {val ?? '—'}
            </div>
          </div>
        ))}
      </div>

      {/* Models + Disk + GPU + Env in a 2-col layout */}
      <div className="mt-5 grid lg:grid-cols-2 gap-5">
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600 mb-2">
            Model artifacts ({data.models.length})
          </div>
          <div className="flex flex-col gap-1">
            {data.models.slice(0, 10).map((m) => (
              <div
                key={m.name}
                className="flex items-center justify-between text-caption py-1 border-b border-white/[0.03] last:border-0"
              >
                <span className="font-mono text-ink-700 truncate mr-3">{m.name}</span>
                <span className="num text-ink-600 shrink-0">
                  {m.size_kb.toFixed(0)} kB · age {m.age_hours.toFixed(1)}h
                </span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600 mb-2">Runtime</div>
          <div className="flex flex-col gap-1 text-caption">
            <div className="flex justify-between border-b border-white/[0.03] py-1">
              <span className="text-ink-700">Disk free</span>
              <span className="num text-ink-800">
                {data.disk.free_gb.toFixed(0)} GB ({data.disk.free_pct.toFixed(0)}%)
              </span>
            </div>
            <div className="flex justify-between border-b border-white/[0.03] py-1">
              <span className="text-ink-700">Disk used</span>
              <span className="num text-ink-600">
                {data.disk.used_gb.toFixed(0)} / {data.disk.total_gb.toFixed(0)} GB
              </span>
            </div>
            <div className="flex justify-between border-b border-white/[0.03] py-1">
              <span className="text-ink-700">GPU</span>
              <span className="num text-ink-800">
                {data.gpu.onnx_directml === true ? 'DirectML detected' : 'CPU only'}
              </span>
            </div>
            <div className="flex justify-between border-b border-white/[0.03] py-1">
              <span className="text-ink-700">CPU</span>
              <span className="num text-ink-600">
                {data.process.cpu_percent != null ? `${data.process.cpu_percent.toFixed(1)}%` : '—'}
              </span>
            </div>
          </div>

          <div className="text-micro uppercase tracking-wider text-ink-600 mt-4 mb-2">
            Env keys
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(data.env).map(([k, ok]) => (
              <span
                key={k}
                className={`pill ${ok ? 'pill-bull' : ''}`}
                style={{ fontSize: 9, opacity: ok ? 1 : 0.55 }}
                title={ok ? 'Set' : 'Missing'}
              >
                {ok ? '✓' : '○'} {k}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
