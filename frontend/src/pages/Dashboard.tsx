import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { api, type Trade, type ScannerInsight as ScanI, type MacroContext } from '@/api/client'
import { Card } from '@/components/Card'
import { Stat } from '@/components/Stat'

export default function Dashboard() {
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio, refetchInterval: 15_000 })
  const { data: ticker } = useQuery({ queryKey: ['ticker'], queryFn: () => api.ticker('XAU/USD'), refetchInterval: 5_000 })
  const { data: trades = [] } = useQuery({ queryKey: ['trades-recent'], queryFn: () => api.trades(10) })
  const { data: insight } = useQuery({ queryKey: ['scanner-insight'], queryFn: api.scannerInsight, refetchInterval: 30_000 })
  const { data: macro } = useQuery({ queryKey: ['macro'], queryFn: api.macroContext, refetchInterval: 60_000 })

  const closed = trades.filter((t) => t.status === 'WIN' || t.status === 'LOSS' || t.status === 'PROFIT' || t.status === 'LOSE')
  const wins = closed.filter((t) => t.status === 'WIN' || t.status === 'PROFIT').length
  const wr = closed.length ? (wins / closed.length) * 100 : null
  const totalPnl = trades.reduce((s, t) => s + (t.profit ?? 0), 0)

  return (
    <div className="flex flex-col gap-12">
      <Hero ticker={ticker} portfolio={portfolio} macro={macro} />

      <section>
        <SectionHeader title="Today" subtitle="Live performance metrics" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-6">
          <Card variant="raised" delay={0.05} className="p-6">
            <Stat
              label="Balance"
              value={portfolio?.balance != null
                ? `${portfolio.balance.toLocaleString(undefined, { maximumFractionDigits: 0 })} ${portfolio.currency || ''}`
                : '—'}
              delta={portfolio?.pnl != null ? { value: portfolio.pnl, suffix: '' } : null}
              hint="vs starting balance"
            />
          </Card>
          <Card variant="raised" delay={0.1} className="p-6">
            <Stat
              label="Win Rate"
              value={wr != null ? `${wr.toFixed(0)}%` : '—'}
              hint={`${closed.length} closed (last 10)`}
            />
          </Card>
          <Card variant="raised" delay={0.15} className="p-6">
            <Stat
              label="Recent P&L"
              value={`${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(0)}`}
              hint="last 10 trades"
            />
          </Card>
          <Card variant="raised" delay={0.2} className="p-6">
            <Stat
              label="Open"
              value={portfolio?.open_positions ?? 0}
              hint="active positions"
            />
          </Card>
        </div>
      </section>

      <div className="grid lg:grid-cols-3 gap-6">
        <Card variant="raised" delay={0.25} className="p-6 lg:col-span-2">
          <SectionHeader title="Recent signals" subtitle="Last 10 trades" inline />
          <div className="mt-6">
            <TradesList trades={trades} />
          </div>
        </Card>
        <Card variant="raised" delay={0.3} className="p-6">
          <SectionHeader title="Scanner" subtitle="Filter activity" inline />
          <div className="mt-6">
            <ScannerPanel insight={insight} />
          </div>
        </Card>
      </div>

      {macro && <MacroStrip macro={macro} />}
    </div>
  )
}

// ─── Hero ─────────────────────────────────────────────────────────────
function Hero({
  ticker,
  portfolio,
  macro,
}: {
  ticker: { price: number; change_pct?: number } | undefined
  portfolio: { balance?: number; pnl?: number; currency?: string } | undefined
  macro: MacroContext | undefined
}) {
  const regime = macro?.macro_regime
  const regimeLabel = regime === 'zielony' ? 'BULL' : regime === 'czerwony' ? 'BEAR' : 'NEUTRAL'
  const regimeColor = regime === 'zielony' ? 'pill-bull' : regime === 'czerwony' ? 'pill-bear' : 'pill'

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      className="relative overflow-hidden rounded-xl3 bg-mesh-gold border border-white/[0.06] p-10 lg:p-16"
    >
      <div className="relative z-10 flex flex-col gap-8">
        <div className="flex flex-wrap gap-2">
          <span className="pill">XAU/USD</span>
          {macro?.market_regime && (
            <span className="pill capitalize">{macro.market_regime.replace('_', ' ')}</span>
          )}
          <span className={regimeColor}>{regimeLabel}</span>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6">
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">
              Spot · gold per ounce
            </div>
            <div className="num font-display text-display-lg text-display-gradient leading-none">
              ${ticker?.price?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? '—'}
            </div>
            {ticker?.change_pct != null && (
              <div className={`mt-3 text-headline num ${ticker.change_pct >= 0 ? 'text-bull' : 'text-bear'}`}>
                {ticker.change_pct >= 0 ? '+' : ''}
                {(ticker.change_pct * 100).toFixed(3)}%
              </div>
            )}
          </div>

          <div className="text-right space-y-1">
            <div className="text-micro uppercase tracking-wider text-ink-600">Account</div>
            <div className="num font-display text-display-sm text-gold-gradient">
              {portfolio?.balance?.toLocaleString(undefined, { maximumFractionDigits: 0 }) ?? '—'}{' '}
              <span className="text-headline opacity-60">{portfolio?.currency}</span>
            </div>
            <div className={`text-body num ${(portfolio?.pnl ?? 0) >= 0 ? 'text-bull' : 'text-bear'}`}>
              {(portfolio?.pnl ?? 0) >= 0 ? '+' : ''}
              {(portfolio?.pnl ?? 0).toFixed(2)} today
            </div>
          </div>
        </div>
      </div>
    </motion.section>
  )
}

function SectionHeader({ title, subtitle, inline }: { title: string; subtitle?: string; inline?: boolean }) {
  return (
    <div className={inline ? 'flex items-baseline gap-3' : ''}>
      <h2 className="text-title text-ink-900 font-display">{title}</h2>
      {subtitle && <p className={`text-caption text-ink-600 ${inline ? '' : 'mt-1'}`}>{subtitle}</p>}
    </div>
  )
}

// ─── Trades list ──────────────────────────────────────────────────────
function TradesList({ trades }: { trades: Trade[] }) {
  if (!trades.length) {
    return <div className="text-caption text-ink-600 py-8 text-center">No recent trades.</div>
  }
  return (
    <div className="flex flex-col">
      {trades.slice(0, 10).map((t, i) => {
        const isWin = t.status === 'WIN' || t.status === 'PROFIT'
        const isLoss = t.status === 'LOSS' || t.status === 'LOSE'
        const isOpen = t.status === 'OPEN' || t.status === 'PROPOSED'
        const isLong = t.direction.toUpperCase().includes('LONG')
        return (
          <div
            key={t.id}
            className={`flex items-center justify-between py-3 ${
              i < trades.length - 1 ? 'border-b border-white/[0.04]' : ''
            }`}
          >
            <div className="flex items-center gap-4 min-w-0 flex-1">
              <span className={`pill ${isLong ? 'pill-bull' : 'pill-bear'} shrink-0`}>
                {isLong ? 'LONG' : 'SHORT'}
              </span>
              <div className="min-w-0">
                <div className="text-body truncate">
                  {t.entry != null ? `$${t.entry.toFixed(2)}` : '—'}{' '}
                  <span className="text-ink-600">→</span>{' '}
                  <span className={isWin ? 'text-bull' : isLoss ? 'text-bear' : 'text-ink-700'}>
                    {t.tp != null ? `$${t.tp.toFixed(2)}` : '—'}
                  </span>
                </div>
                <div className="text-caption text-ink-600 truncate">
                  {t.pattern || t.timeframe || '—'} ·{' '}
                  {new Date(t.timestamp).toLocaleString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </div>
              </div>
            </div>
            <div className="text-right shrink-0 ml-4">
              <div className={`num text-body ${isWin ? 'text-bull' : isLoss ? 'text-bear' : 'text-ink-700'}`}>
                {t.profit != null
                  ? `${t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}`
                  : isOpen
                  ? 'open'
                  : '—'}
              </div>
              <div className="text-micro text-ink-600 uppercase tracking-wider">{t.status}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Scanner panel ────────────────────────────────────────────────────
function ScannerPanel({ insight }: { insight: ScanI | undefined }) {
  if (!insight) {
    return <div className="text-caption text-ink-600 py-4">Waiting for scanner data…</div>
  }
  const rejections = insight.rejections?.top?.slice(0, 5) ?? []
  const toxic = insight.toxic_patterns?.slice(0, 3) ?? []
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between text-caption">
        <span className="text-ink-600">Window</span>
        <span className="num text-ink-800">{insight.hours_window}h</span>
      </div>
      <div className="flex items-center justify-between text-caption">
        <span className="text-ink-600">Rejections (total)</span>
        <span className="num text-ink-800">{insight.rejections?.total ?? 0}</span>
      </div>
      <div>
        <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">Top filters</div>
        {rejections.length === 0 ? (
          <div className="text-caption text-ink-600">Quiet window.</div>
        ) : (
          <div className="flex flex-col gap-2">
            {rejections.map((r, i) => (
              <div key={i} className="flex items-center justify-between text-caption">
                <span className="truncate text-ink-700">{r.filter}</span>
                <span className="num text-ink-600 shrink-0 ml-3">{r.count}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {toxic.length > 0 && (
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">Toxic watch</div>
          <div className="flex flex-col gap-2">
            {toxic.map((p, i) => (
              <div key={i} className="text-caption flex items-center justify-between">
                <span className="truncate text-ink-700 mr-2">{p.pattern}</span>
                <span className={`num shrink-0 ${p.win_rate < 0.3 ? 'text-bear' : 'text-ink-600'}`}>
                  {Math.round(p.win_rate * 100)}% · n={p.n}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Macro strip ──────────────────────────────────────────────────────
function MacroStrip({ macro }: { macro: MacroContext }) {
  return (
    <Card variant="flat" delay={0.4} className="p-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">USD/JPY z-score</div>
          <div className="num text-headline mt-1">{macro.usdjpy_zscore?.toFixed(2) ?? '—'}</div>
        </div>
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">XAU·USDJPY corr</div>
          <div className="num text-headline mt-1">{macro.xau_usdjpy_corr != null ? macro.xau_usdjpy_corr.toFixed(2) : '—'}</div>
        </div>
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">Macro regime</div>
          <div className="text-body mt-1 capitalize">
            {macro.macro_regime === 'zielony' ? 'bullish gold' : macro.macro_regime === 'czerwony' ? 'bearish gold' : 'neutral'}
          </div>
        </div>
        <div>
          <div className="text-micro uppercase tracking-wider text-ink-600">Market</div>
          <div className="text-body mt-1 capitalize">{macro.market_regime?.replace('_', ' ') ?? '—'}</div>
        </div>
      </div>
    </Card>
  )
}
