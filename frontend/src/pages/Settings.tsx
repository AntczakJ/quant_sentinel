import { useQuery } from '@tanstack/react-query'
import NumberFlow from '@number-flow/react'
import { api } from '@/api/client'
import { Card } from '@/components/Card'
import { AuroraBackground } from '@/components/AuroraBackground'
import { FeatureFlagsPanel } from '@/components/FeatureFlagsPanel'
import { GradientText } from '@/components/GradientText'
import { TextReveal } from '@/components/TextReveal'
import { TiltCard } from '@/components/TiltCard'
import { Spotlight } from '@/components/Spotlight'
import { useEffect, useMemo, useState } from 'react'
import { isSoundEnabled, setSoundEnabled } from '@/lib/sound'

export default function Settings() {
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health })
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })

  const [soundOn, setSoundOn] = useState(false)
  useEffect(() => setSoundOn(isSoundEnabled()), [])

  return (
    <div className="relative flex flex-col gap-8 overflow-visible">
      {/* Full-viewport aurora — escape the max-w container by using fixed
          positioning instead of absolute. Sits below content (z-[-10])
          and above the global mesh background. */}
      <div className="fixed inset-0 -z-10 overflow-hidden pointer-events-none">
        <AuroraBackground intensity={0.55} />
      </div>

      <header className="reveal-on-scroll">
        <h1 className="text-display-sm font-display tracking-tight">
          <GradientText>
            <TextReveal text="Settings" splitBy="char" />
          </GradientText>
        </h1>
        <p className="text-body text-ink-600 mt-2">
          <TextReveal text="System configuration and live state." delay={0.18} />
        </p>
      </header>

      <div className="grid lg:grid-cols-2 gap-4 reveal-on-scroll">
        <TiltCard className="rounded-xl" intensity={6}>
          <Card variant="raised" className="relative overflow-hidden p-6">
            <Spotlight color="rgba(212,175,55,0.16)" />
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
        </TiltCard>

        <TiltCard className="rounded-xl" intensity={6}>
          <Card variant="raised" className="relative overflow-hidden p-6">
            <Spotlight color="rgba(59,130,246,0.16)" />
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
        </TiltCard>

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

        {/* ─── Feature flags + dynamic params (2026-05-04) ─ */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <h3 className="text-h3 mb-5">Feature flags &amp; runtime params</h3>
          <FeatureFlagsPanel />
        </Card>

        {/* ─── Recommendations — heuristic next-step suggestions ─ */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <RecommendationsBlock />
        </Card>

        {/* ─── External services (Logfire / Sentry / Modal) ── */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <ExternalServicesBlock />
        </Card>

        {/* ─── Modal cron schedule preview ───────────────────── */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <CronScheduleBlock />
        </Card>

        {/* ─── Rate limit (API credits) ──────────────────────── */}
        <Card variant="raised" className="p-6">
          <RateLimitBlock />
        </Card>

        {/* ─── Macro regime history ────────────────────────── */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <MacroRegimeBlock />
        </Card>

        {/* ─── Database stats ───────────────────────────────── */}
        <Card variant="raised" className="p-6">
          <DbStatsBlock />
        </Card>

        {/* ─── Scanner peek ─────────────────────────────────── */}
        <Card variant="raised" className="p-6 lg:col-span-2">
          <ScannerPeekBlock />
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

// ─── Modal cron preview — next fire of "0 3 * * 0" ─────────────────
function CronScheduleBlock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(t)
  }, [])

  // "0 3 * * 0" = Sunday 03:00 UTC
  const next = useMemo(() => {
    const r = new Date(now)
    r.setUTCSeconds(0, 0)
    r.setUTCMinutes(0)
    r.setUTCHours(3)
    let daysUntilSunday = (7 - r.getUTCDay()) % 7
    if (daysUntilSunday === 0 && now.getTime() >= r.getTime()) {
      daysUntilSunday = 7
    }
    r.setUTCDate(r.getUTCDate() + daysUntilSunday)
    return r
  }, [now])

  const deltaMs = next.getTime() - now.getTime()
  const days = Math.floor(deltaMs / (24 * 3600_000))
  const hours = Math.floor((deltaMs % (24 * 3600_000)) / 3600_000)
  const mins = Math.floor((deltaMs % 3600_000) / 60_000)

  const localStr = next.toLocaleString(undefined, {
    weekday: 'long', year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  })

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-title font-display">Modal weekly retrain</h3>
          <p className="text-caption text-ink-600 mt-1">
            Next fire computed locally from the cron expression baked into <span className="font-mono">tools/modal_train.py</span>.
            Modal triggers <span className="font-mono">run()</span> at this moment without your laptop being on.
          </p>
        </div>
        <span className="pill" style={{ fontSize: 11 }}>0 3 * * 0</span>
      </div>

      <div className="mt-4 grid sm:grid-cols-3 gap-3">
        <div className="surface p-3 rounded-xl">
          <div className="text-micro uppercase tracking-wider text-ink-600">Next fire (your time)</div>
          <div className="num text-body mt-0.5 text-ink-900">{localStr}</div>
        </div>
        <div className="surface p-3 rounded-xl">
          <div className="text-micro uppercase tracking-wider text-ink-600">Next fire (UTC)</div>
          <div className="num text-body mt-0.5 text-ink-900">
            {next.toISOString().replace('T', ' ').slice(0, 16)} UTC
          </div>
        </div>
        <div className="surface p-3 rounded-xl">
          <div className="text-micro uppercase tracking-wider text-ink-600">Time until</div>
          <div className="num text-body mt-0.5 text-gold-400">
            {days > 0 ? `${days}d ` : ''}{hours}h {mins}m
          </div>
        </div>
      </div>

      <p className="text-micro text-ink-600 mt-3">
        Change cadence: edit <span className="font-mono">tools/modal_train.py</span> →
        <span className="font-mono"> schedule=modal.Cron("0 3 * * *")</span> for daily, then
        <span className="font-mono"> .venv/Scripts/modal deploy tools/modal_train.py</span>.
      </p>
    </div>
  )
}

// ─── Recommendations — heuristic next-step suggestions ──────────────
function RecommendationsBlock() {
  const { data } = useQuery({
    queryKey: ['recommendations'],
    queryFn: api.recommendations,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  const sevToTone = (sev: string) =>
    sev === 'error' ? 'pill-bear' : sev === 'warn' ? 'pill border-gold-500/30 bg-gold-500/[0.08] text-gold-400' : 'pill'

  if (!data) {
    return (
      <div>
        <h3 className="text-title font-display">Recommendations</h3>
        <p className="text-caption text-ink-600 mt-2">Loading…</p>
      </div>
    )
  }

  if (data.count === 0) {
    return (
      <div>
        <h3 className="text-title font-display">Recommendations</h3>
        <p className="text-caption text-ink-600 mt-2 flex items-center gap-2">
          <span className="pill pill-bull" style={{ fontSize: 11 }}>ALL CLEAR</span>
          Nothing flagged — every soft-check passed.
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-title font-display">Recommendations</h3>
        <div className="flex items-center gap-2 text-micro uppercase tracking-wider">
          {data.by_severity.error > 0 && (
            <span className="pill pill-bear" style={{ fontSize: 9 }}>{data.by_severity.error} ERR</span>
          )}
          {data.by_severity.warn > 0 && (
            <span className="pill border-gold-500/30 bg-gold-500/[0.08] text-gold-400" style={{ fontSize: 9 }}>
              {data.by_severity.warn} WARN
            </span>
          )}
          {data.by_severity.info > 0 && (
            <span className="pill" style={{ fontSize: 9 }}>{data.by_severity.info} INFO</span>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-col gap-2">
        {data.items.map((item) => (
          <div key={item.id} className="surface p-3 rounded-xl flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className={sevToTone(item.severity)} style={{ fontSize: 9 }}>
                  {item.severity.toUpperCase()}
                </span>
                <span className="text-body text-ink-900 font-medium truncate">{item.title}</span>
              </div>
              <p className="text-caption text-ink-600 mt-1">{item.detail}</p>
            </div>
            {item.action_url && (
              <button
                type="button"
                onClick={() => window.open(item.action_url, '_blank', 'noopener,noreferrer')}
                className="px-3 py-1.5 rounded-full text-caption border border-white/10 bg-white/[0.03] hover:border-white/25 hover:bg-white/[0.06] transition-all shrink-0"
              >
                Open ↗
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Scanner diagnostic — what would the scanner see right now ────────
function ScannerPeekBlock() {
  const [view, setView] = useState<'single' | 'all'>('single')
  const [tf, setTf] = useState<'5m' | '15m' | '30m' | '1h' | '4h'>('15m')
  const { data, isError } = useQuery({
    queryKey: ['scanner-peek', tf],
    queryFn: () => api.scannerPeek('XAU/USD', tf, 100),
    refetchInterval: view === 'single' ? 30_000 : false,
    staleTime: 15_000,
    enabled: view === 'single',
  })
  const { data: allData, isError: allErr } = useQuery({
    queryKey: ['scanner-peek-all'],
    queryFn: () => api.scannerPeekAll('XAU/USD', 100),
    refetchInterval: view === 'all' ? 60_000 : false,
    staleTime: 30_000,
    enabled: view === 'all',
  })

  const biasClass = data?.bias === 'bullish' ? 'pill-bull'
    : data?.bias === 'bearish' ? 'pill-bear' : 'pill'

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-title font-display">Scanner peek · XAU/USD</h3>
          <p className="text-caption text-ink-600 mt-1">
            Indicators on the latest 100 bars — no SMC, no ML, no DB write. Useful when asking
            "why no trade today?".
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <div className="flex gap-1 mr-2">
            <button
              onClick={() => setView('single')}
              className={`px-2.5 py-1 rounded-full text-micro uppercase tracking-wider transition-colors ${
                view === 'single' ? 'bg-white/[0.08] text-ink-900 border border-white/15' : 'border border-white/[0.06] text-ink-600 hover:border-white/15'
              }`}
            >Single</button>
            <button
              onClick={() => setView('all')}
              className={`px-2.5 py-1 rounded-full text-micro uppercase tracking-wider transition-colors ${
                view === 'all' ? 'bg-white/[0.08] text-ink-900 border border-white/15' : 'border border-white/[0.06] text-ink-600 hover:border-white/15'
              }`}
            >All TFs</button>
          </div>
          {view === 'single' && (
            <div className="flex gap-1">
              {(['5m', '15m', '30m', '1h', '4h'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTf(t)}
                  className={`px-2.5 py-1 rounded-full text-micro uppercase tracking-wider transition-colors ${
                    tf === t
                      ? 'bg-white/[0.08] text-ink-900 border border-white/15'
                      : 'border border-white/[0.06] text-ink-600 hover:border-white/15'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* All-TFs view */}
      {view === 'all' && (
        <>
          {allErr && <p className="text-caption text-bear mt-3">/api/scanner/peek-all failed.</p>}
          {allData && (
            <>
              <div className="mt-4 flex items-center gap-3 flex-wrap">
                <span className={`pill ${
                  allData.agreement.label.includes('bull') ? 'pill-bull' :
                  allData.agreement.label.includes('bear') ? 'pill-bear' : ''
                }`} style={{ fontSize: 11 }}>
                  {allData.agreement.label.replace('_', ' ').toUpperCase()}
                </span>
                <span className="text-caption text-ink-600">
                  bull {allData.agreement.bull_count} · bear {allData.agreement.bear_count} · neutral {allData.agreement.neutral_count}
                </span>
                {allData.agreement.tfs_failed.length > 0 && (
                  <span className="text-caption text-bear">
                    failed: {allData.agreement.tfs_failed.join(', ')}
                  </span>
                )}
              </div>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-caption">
                  <thead>
                    <tr className="border-b border-white/[0.04] text-micro uppercase tracking-wider text-ink-600">
                      <th className="text-left py-2 px-2">TF</th>
                      <th className="text-right py-2 px-2">Close</th>
                      <th className="text-right py-2 px-2">RSI</th>
                      <th className="text-right py-2 px-2">ATR</th>
                      <th className="text-right py-2 px-2">EMA dist</th>
                      <th className="text-right py-2 px-2">Range</th>
                      <th className="text-right py-2 px-2">Bias</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(['5m', '15m', '30m', '1h', '4h'] as const).map((t) => {
                      const r = allData.by_tf[t]
                      if (!r) {
                        return (
                          <tr key={t} className="border-b border-white/[0.03]">
                            <td className="py-2 px-2 num text-ink-700">{t}</td>
                            <td colSpan={6} className="py-2 px-2 text-ink-600 italic">{allData.errors[t] ?? '—'}</td>
                          </tr>
                        )
                      }
                      const dist = r.indicators.ema_distance_pct
                      const rangePct = ((r.indicators.high_14 - r.indicators.low_14) / r.indicators.low_14 * 100)
                      return (
                        <tr key={t} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                          <td className="py-2 px-2 num text-ink-800 font-medium">{t}</td>
                          <td className="py-2 px-2 num text-right">${r.last_bar.close.toFixed(2)}</td>
                          <td className={`py-2 px-2 num text-right ${
                            r.indicators.rsi_14 > 70 ? 'text-bear' :
                            r.indicators.rsi_14 < 30 ? 'text-bull' : 'text-ink-700'
                          }`}>{r.indicators.rsi_14.toFixed(1)}</td>
                          <td className="py-2 px-2 num text-right text-ink-700">{r.indicators.atr_14.toFixed(2)}</td>
                          <td className={`py-2 px-2 num text-right ${dist > 0 ? 'text-bull' : 'text-bear'}`}>
                            {dist >= 0 ? '+' : ''}{dist.toFixed(3)}%
                          </td>
                          <td className="py-2 px-2 num text-right text-ink-700">{rangePct.toFixed(2)}%</td>
                          <td className="py-2 px-2 text-right">
                            <span className={`pill ${
                              r.bias === 'bullish' ? 'pill-bull' :
                              r.bias === 'bearish' ? 'pill-bear' : ''
                            }`} style={{ fontSize: 9 }}>
                              {r.bias.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}

      {/* Single-TF view */}
      {view === 'single' && isError && <p className="text-caption text-bear mt-3">/api/scanner/peek failed.</p>}
      {view === 'single' && data && (
        <>
          <div className="mt-4 flex items-center gap-3 flex-wrap">
            <span className={biasClass} style={{ fontSize: 11 }}>
              {data.bias.toUpperCase()}
            </span>
            <span className="text-caption text-ink-600">
              last bar: <span className="num text-ink-800">{data.last_bar.ts}</span>
            </span>
            <span className="text-caption text-ink-600">
              close <span className="num text-ink-900">${data.last_bar.close.toFixed(2)}</span>
            </span>
          </div>

          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <PeekStat label="RSI 14"
                      value={data.indicators.rsi_14.toFixed(1)}
                      tone={data.indicators.rsi_14 > 70 ? 'bear' : data.indicators.rsi_14 < 30 ? 'bull' : undefined} />
            <PeekStat label="ATR 14" value={data.indicators.atr_14.toFixed(2)} />
            <PeekStat label="EMA-20 distance"
                      value={`${data.indicators.ema_distance_pct >= 0 ? '+' : ''}${data.indicators.ema_distance_pct.toFixed(3)}%`}
                      tone={data.indicators.ema_distance_pct > 0 ? 'bull' : 'bear'} />
            <PeekStat label="Volatility 20"
                      value={(data.indicators.volatility_20 * 100).toFixed(3) + '%'} />
            <PeekStat label="14-bar high"
                      value={'$' + data.indicators.high_14.toFixed(2)} />
            <PeekStat label="14-bar low"
                      value={'$' + data.indicators.low_14.toFixed(2)} />
            <PeekStat label="Range %"
                      value={((data.indicators.high_14 - data.indicators.low_14) / data.indicators.low_14 * 100).toFixed(2) + '%'} />
            <PeekStat label="Position in range"
                      value={(((data.last_bar.close - data.indicators.low_14)
                              / (data.indicators.high_14 - data.indicators.low_14)) * 100).toFixed(0) + '%'} />
          </div>
        </>
      )}
    </div>
  )
}

function PeekStat({ label, value, tone }: { label: string; value: string; tone?: 'bull' | 'bear' }) {
  const cls = tone === 'bull' ? 'text-bull' : tone === 'bear' ? 'text-bear' : 'text-ink-900'
  return (
    <div className="surface p-3 rounded-xl">
      <div className="text-micro uppercase tracking-wider text-ink-600">{label}</div>
      <div className={`num text-body mt-0.5 ${cls}`}>{value}</div>
    </div>
  )
}

// ─── External services panel ─────────────────────────────────────────
function ExternalServicesBlock() {
  const { data } = useQuery({
    queryKey: ['system-info'],
    queryFn: api.systemInfo,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  const integ = data?.integrations
  const services = [
    { key: 'logfire' as const, name: 'Logfire',
      tagline: 'Observability — request traces + scanner spans',
      logo: '🔍', color: 'border-info/30' },
    { key: 'sentry' as const, name: 'Sentry',
      tagline: 'Error tracking — captured exceptions + cron heartbeats',
      logo: '🚨', color: 'border-bear/30' },
    { key: 'modal' as const, name: 'Modal Labs',
      tagline: 'Cloud GPU — weekly retrain Sun 03:00 UTC',
      logo: '🚀', color: 'border-gold-500/30' },
  ]

  return (
    <div>
      <h3 className="text-title font-display">External services</h3>
      <p className="text-caption text-ink-600 mt-1">
        Status loaded from <span className="font-mono">/api/system/integrations</span>.
        Click "Open" to jump to the dashboard.
      </p>
      <div className="mt-4 grid sm:grid-cols-3 gap-3">
        {services.map((s) => {
          const cfg = integ?.[s.key]
          const active = cfg?.active ?? false
          return (
            <div
              key={s.key}
              className={`rounded-xl2 p-4 bg-ink-100 border ${s.color} flex flex-col gap-3`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-headline">{s.logo}</span>
                  <div className="min-w-0">
                    <div className="text-body text-ink-900 font-medium truncate">{s.name}</div>
                    <div className="text-micro text-ink-600 truncate">{cfg?.what ?? s.tagline}</div>
                  </div>
                </div>
                <span className={`pill shrink-0 ${active ? 'pill-bull' : ''}`} style={{ fontSize: 9 }}>
                  {active ? '✓ ACTIVE' : '○ inactive'}
                </span>
              </div>
              <button
                type="button"
                onClick={() => cfg?.url && window.open(cfg.url, '_blank', 'noopener,noreferrer')}
                disabled={!cfg?.url}
                className="px-3 py-1.5 rounded-full text-caption border border-white/10 bg-white/[0.03] hover:border-white/25 hover:bg-white/[0.06] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Open dashboard ↗
              </button>
            </div>
          )
        })}
      </div>
      {!integ && (
        <div className="text-caption text-ink-600 mt-3">
          Loading service status…
        </div>
      )}
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

  // Usage-oriented view: bar fills as credits are spent in the rolling minute.
  // Color ramps green → gold (≥ alarm) → bear (≥ safe-limit hard guard).
  const used = data.credits_used_last_min
  const max = data.max_limit
  const safe = data.safe_limit
  const alarm = data.alarm_threshold ?? 45
  const usedPct = max > 0 ? (used / max) * 100 : 0
  const alarmPct = max > 0 ? (alarm / max) * 100 : 0
  const safePct = max > 0 ? (safe / max) * 100 : 100

  const tone = used >= safe ? 'bear' : used >= alarm ? 'gold' : 'bull'
  const toneClass = tone === 'bear' ? 'text-bear' : tone === 'gold' ? 'text-gold-400' : 'text-bull'
  const fillBg = tone === 'bear' ? 'bg-bear/70' : tone === 'gold' ? 'bg-gold-500/70' : 'bg-bull/70'

  const lastAlarmAge = data.last_alarm_ts && data.last_alarm_ts > 0
    ? Math.max(0, Math.round(Date.now() / 1000 - data.last_alarm_ts))
    : null
  const cooldownSec = data.alarm_cooldown_sec ?? 300
  const inCooldown = lastAlarmAge !== null && lastAlarmAge < cooldownSec

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-title font-display">API credits</h3>
          <p className="text-caption text-ink-600 mt-1">
            TwelveData primary bucket · {data.current_credits}/{safe} available
          </p>
        </div>
        <div className="text-right">
          <div className="text-micro uppercase tracking-wider text-ink-600">Used / min</div>
          <div className={`num text-headline font-display ${toneClass}`}>
            <NumberFlow
              value={used}
              format={{ maximumFractionDigits: 0 }}
              respectMotionPreference
            />
            <span className="text-caption text-ink-600"> / {max}</span>
          </div>
        </div>
      </div>

      {/* Usage bar — fills as credits are spent in the rolling minute */}
      <div className="mt-4 relative h-2 rounded-full bg-white/[0.04] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${fillBg}`}
          style={{ width: `${Math.min(100, usedPct)}%` }}
        />
        {/* Alarm-threshold marker (gold) */}
        <div
          className="absolute top-0 bottom-0 w-px bg-gold-400/60"
          style={{ left: `${Math.min(100, alarmPct)}%` }}
          title={`alarm: ${alarm}/min`}
        />
        {/* Safe-limit marker (red — skip-cycle guard) */}
        <div
          className="absolute top-0 bottom-0 w-px bg-bear/70"
          style={{ left: `${Math.min(100, safePct)}%` }}
          title={`skip-cycle guard: ${safe}/min`}
        />
      </div>

      {/* Threshold legend */}
      <div className="mt-2 flex items-center gap-4 text-micro text-ink-600">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-bull/70" />
          0–{alarm - 1} OK
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-gold-500/70" />
          {alarm}–{safe - 1} warn
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-bear/70" />
          ≥{safe} skip-cycle
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-4 text-caption">
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
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">Last alarm</div>
          <div className="num text-body mt-0.5">
            {lastAlarmAge === null
              ? <span className="text-ink-600">—</span>
              : inCooldown
                ? <span className="text-gold-400">{lastAlarmAge}s ago</span>
                : <span className="text-ink-600">{Math.round(lastAlarmAge / 60)}m ago</span>}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Macro regime history strip ────────────────────────────────────────
function MacroRegimeBlock() {
  const { data, isError } = useQuery({
    queryKey: ['macro-snapshots'],
    queryFn: () => api.macroSnapshots(96),  // ~8h of 5-min snapshots
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  if (isError) {
    return (
      <div>
        <h3 className="text-title font-display">Macro regime</h3>
        <p className="text-caption text-bear mt-2">/api/macro/snapshots failed.</p>
      </div>
    )
  }

  const items = data?.items ?? []
  // API returns newest-first. Reverse for left-to-right oldest-first display.
  const ordered = [...items].reverse()
  const latest = items[0]   // newest

  // Color per regime — matches design token vocabulary used elsewhere
  const colorFor = (regime: string | null | undefined) => {
    if (regime === 'zielony') return 'bg-bull/70'
    if (regime === 'czerwony') return 'bg-bear/70'
    if (regime === 'neutralny') return 'bg-ink-600/40'
    return 'bg-white/[0.04]'   // unknown / no data
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-title font-display">Macro regime</h3>
          <p className="text-caption text-ink-600 mt-1">
            Per-cycle persistence · {ordered.length} samples shown
            {ordered.length === 0 && ' · awaiting next API restart to start collecting'}
          </p>
        </div>
        {latest && (
          <div className="text-right">
            <div className="text-micro uppercase tracking-wider text-ink-600">Now</div>
            <div className="text-headline font-display capitalize">
              <span className={
                latest.macro_regime === 'zielony' ? 'text-bull' :
                latest.macro_regime === 'czerwony' ? 'text-bear' :
                'text-ink-700'
              }>
                {latest.macro_regime ?? '—'}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Strip: one cell per snapshot */}
      <div className="mt-4 flex gap-[2px] h-6 rounded-md overflow-hidden bg-white/[0.02]">
        {ordered.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-micro text-ink-600">
            No snapshots yet — table populates after API restart picks up the new BG task.
          </div>
        ) : ordered.map((snap) => (
          <div
            key={snap.id}
            className={`flex-1 ${colorFor(snap.macro_regime)} transition-all`}
            title={`${snap.timestamp} — ${snap.macro_regime ?? 'unknown'}\n` +
                   `USDJPY z=${snap.usdjpy_zscore?.toFixed(2) ?? '—'}\n` +
                   `ATR ratio=${snap.atr_ratio?.toFixed(2) ?? '—'}\n` +
                   `Market regime: ${snap.market_regime ?? '—'}`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="mt-3 flex items-center gap-4 text-micro text-ink-600">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-bull/70" />
          zielony (gold-bullish)
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-bear/70" />
          czerwony (gold-bearish)
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-ink-600/40" />
          neutralny (mixed)
        </span>
      </div>

      {/* Live numerics */}
      {latest && (
        <div className="mt-4 grid grid-cols-3 gap-4 text-caption">
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600">USDJPY z</div>
            <div className="num text-body mt-0.5">
              {latest.usdjpy_zscore != null
                ? <NumberFlow value={latest.usdjpy_zscore} format={{ maximumFractionDigits: 2 }} respectMotionPreference />
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600">ATR ratio</div>
            <div className="num text-body mt-0.5">
              {latest.atr_ratio != null
                ? <NumberFlow value={latest.atr_ratio} format={{ maximumFractionDigits: 2 }} respectMotionPreference />
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600">Market</div>
            <div className="text-body mt-0.5 capitalize">
              {latest.market_regime ?? '—'}
            </div>
          </div>
        </div>
      )}
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
