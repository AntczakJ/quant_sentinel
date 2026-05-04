import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import NumberFlow from '@number-flow/react'
import {
  api,
  type Trade,
  type ScannerInsight as ScanI,
  type MacroContext,
} from '@/api/client'
import { Stat } from '@/components/Stat'
import { FlashOnChange } from '@/components/FlashOnChange'
import { ExpandableCard } from '@/components/ExpandableCard'
import { Sparkline } from '@/components/Sparkline'
import { RiskHaltBanner } from '@/components/RiskHaltBanner'
import { TiltCard } from '@/components/TiltCard'
import { LiveDot } from '@/components/LiveDot'
import { GradientText } from '@/components/GradientText'
import { BlobField } from '@/components/BlobField'
import { Marquee } from '@/components/Marquee'
import { StaggerReveal } from '@/components/StaggerReveal'
import { ConfettiBurst } from '@/components/ConfettiBurst'
import { useEffect, useRef, useState } from 'react'
import { isSoundEnabled, playWin, playLoss } from '@/lib/sound'

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

  // Trend series for bento sparklines — derived from chronologically-sorted closed trades
  const closedAsc = [...closed].reverse() // api returns newest-first; we want oldest-first
  const wrSeries: number[] = []
  let cumWins = 0
  closedAsc.forEach((t, i) => {
    if (t.status === 'WIN' || t.status === 'PROFIT') cumWins += 1
    wrSeries.push((cumWins / (i + 1)) * 100)
  })
  const pnlSeries: number[] = []
  let cumPnl = 0
  closedAsc.forEach((t) => {
    cumPnl += t.profit ?? 0
    pnlSeries.push(cumPnl)
  })

  // Confetti trigger — fires once per new winning trade
  const lastWinIdRef = useRef<number | null>(null)
  const lastLossIdRef = useRef<number | null>(null)
  const [winBurst, setWinBurst] = useState(0)
  useEffect(() => {
    const winners = trades.filter((t) => t.status === 'WIN' || t.status === 'PROFIT')
    if (winners.length) {
      const newest = winners[0].id ?? null
      if (lastWinIdRef.current === null) {
        lastWinIdRef.current = newest
      } else if (newest !== lastWinIdRef.current) {
        lastWinIdRef.current = newest
        setWinBurst((b) => b + 1)
        if (isSoundEnabled()) playWin()
      }
    }
    const losers = trades.filter((t) => t.status === 'LOSS' || t.status === 'LOSE')
    if (losers.length) {
      const newest = losers[0].id ?? null
      if (lastLossIdRef.current === null) {
        lastLossIdRef.current = newest
      } else if (newest !== lastLossIdRef.current) {
        lastLossIdRef.current = newest
        if (isSoundEnabled()) playLoss()
      }
    }
  }, [trades])

  return (
    <div className="flex flex-col gap-10">
      <RiskHaltBanner />
      <Hero ticker={ticker} portfolio={portfolio} macro={macro} winBurst={winBurst} />

      {/* ─── Live ticker marquee — XAU + recent trades ─────────────── */}
      <TickerMarquee ticker={ticker} trades={trades.slice(0, 8)} />

      {/* ─── Bento KPI grid ───────────────────────────────────────────── */}
      <section className="reveal-on-scroll">
        <SectionHeader title="Today" subtitle="Live performance metrics" />

        <div className="mt-6 grid grid-cols-12 auto-rows-[140px] gap-4">
          {/* Balance — 6×2 hero KPI */}
          <ExpandableCard
            id="kpi-balance"
            accent="gold"
            className="col-span-12 md:col-span-6 row-span-2 p-7 flex flex-col justify-between"
            detailTitle="Balance & equity"
            detail={
              <BalanceDetail
                balance={portfolio?.balance}
                pnl={portfolio?.pnl}
                pnlPct={portfolio?.pnl_pct}
                currency={portfolio?.currency}
              />
            }
          >
            <Stat
              label="Balance"
              size="lg"
              numeric={portfolio?.balance ?? null}
              format={{ style: 'decimal', maximumFractionDigits: 0 }}
              suffix={portfolio?.currency ? ` ${portfolio.currency}` : ''}
              delta={portfolio?.pnl != null ? { value: portfolio.pnl, suffix: '' } : null}
              hint="vs starting balance"
            />
            {portfolio?.pnl_pct != null && (
              <div className="text-caption text-ink-600 mt-2">
                <NumberFlow
                  value={portfolio.pnl_pct}
                  format={{ minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }}
                  suffix="% net"
                  respectMotionPreference
                />
              </div>
            )}
          </ExpandableCard>

          {/* Win Rate — 3×1 */}
          <ExpandableCard
            id="kpi-wr"
            className="col-span-6 md:col-span-3 p-6 flex flex-col justify-between"
            detailTitle="Win-rate breakdown"
            detail={<WinRateDetail trades={trades} wr={wr} closed={closed.length} />}
          >
            <Stat
              label="Win Rate"
              numeric={wr}
              format={{ style: 'decimal', maximumFractionDigits: 0 }}
              suffix="%"
              hint={`${closed.length} closed (last 10)`}
            />
            {wrSeries.length >= 2 && (
              <div className="mt-3 -mb-1">
                <Sparkline
                  values={wrSeries}
                  width={220}
                  height={32}
                  color="#a1a1aa"
                  strokeWidth={1.4}
                  ariaLabel="rolling win-rate"
                />
              </div>
            )}
          </ExpandableCard>

          {/* Recent P&L — 3×1 */}
          <ExpandableCard
            id="kpi-pnl"
            accent={totalPnl > 0 ? 'bull' : totalPnl < 0 ? 'bear' : 'none'}
            className="col-span-6 md:col-span-3 p-6 flex flex-col justify-between"
            detailTitle="Recent P&L"
            detail={<RecentPnlDetail trades={trades} total={totalPnl} />}
          >
            <Stat
              label="Recent P&L"
              numeric={totalPnl}
              format={{ style: 'decimal', maximumFractionDigits: 0, signDisplay: 'exceptZero' }}
              hint="last 10 trades"
            />
            {pnlSeries.length >= 2 && (
              <div className="mt-3 -mb-1">
                <Sparkline
                  values={pnlSeries}
                  width={220}
                  height={32}
                  zeroLine
                  strokeWidth={1.6}
                  ariaLabel="cumulative P&L"
                />
              </div>
            )}
          </ExpandableCard>

          {/* Open positions — 3×1 */}
          <ExpandableCard
            id="kpi-open"
            className="col-span-6 md:col-span-3 p-6"
            detailTitle="Open positions"
            detail={<OpenPositionsDetail />}
          >
            <Stat
              label="Open"
              numeric={portfolio?.open_positions ?? 0}
              format={{ style: 'decimal', maximumFractionDigits: 0 }}
              hint="active positions"
            />
          </ExpandableCard>

          {/* Macro mini-strip — 9×1 */}
          {macro && (
            <ExpandableCard
              id="kpi-macro"
              className="col-span-12 md:col-span-9 p-6"
              detailTitle="Macro context"
              detail={<MacroDetail macro={macro} />}
            >
              <MacroMini macro={macro} />
            </ExpandableCard>
          )}
        </div>
      </section>

      {/* ─── Recent signals + Scanner ─────────────────────────────────── */}
      <section className="reveal-on-scroll grid grid-cols-12 gap-4">
        <ExpandableCard
          id="recent-signals"
          className="col-span-12 lg:col-span-8 p-6"
          detailTitle="Recent signals — full detail"
          detail={<TradesList trades={trades} expanded />}
        >
          <SectionHeader title="Recent signals" subtitle="Last 10 trades" inline />
          <div className="mt-5">
            <TradesList trades={trades} />
          </div>
        </ExpandableCard>

        <ExpandableCard
          id="scanner"
          className="col-span-12 lg:col-span-4 p-6"
          detailTitle="Scanner activity"
          detail={<ScannerPanel insight={insight} expanded />}
        >
          <SectionHeader title="Scanner" subtitle="Filter activity" inline />
          <div className="mt-5">
            <ScannerPanel insight={insight} />
          </div>
        </ExpandableCard>
      </section>
    </div>
  )
}

// ─── Hero ─────────────────────────────────────────────────────────────
function Hero({
  ticker,
  portfolio,
  macro,
  winBurst = 0,
}: {
  ticker: { price: number; change_pct?: number } | undefined
  portfolio: { balance?: number; pnl?: number; currency?: string } | undefined
  macro: MacroContext | undefined
  winBurst?: number
}) {
  const regime = macro?.macro_regime
  const regimeLabel = regime === 'zielony' ? 'BULL' : regime === 'czerwony' ? 'BEAR' : 'NEUTRAL'
  const regimeColor = regime === 'zielony' ? 'pill-bull' : regime === 'czerwony' ? 'pill-bear' : 'pill'

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      className="surface-grain relative overflow-hidden rounded-xl3 bg-mesh-gold border border-white/[0.06] p-10 lg:p-16"
    >
      <BlobField variant="mixed" />
      <ConfettiBurst trigger={winBurst} count={36} origin={{ x: '50%', y: '40%' }} />
      <div className="relative z-10 flex flex-col gap-8">
        <div className="flex flex-wrap items-center gap-2">
          <LiveDot label="LIVE" color="bull" />
          <span className="pill">XAU/USD</span>
          {macro?.market_regime && (
            <span className="pill capitalize">{macro.market_regime.replace('_', ' ')}</span>
          )}
          <span className={regimeColor}>{regimeLabel}</span>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6">
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">
              <GradientText>Spot · gold per ounce</GradientText>
            </div>
            <div
              className="num font-display text-display-lg text-ink-900 leading-none"
              style={{ viewTransitionName: 'hero-price' }}
            >
              <FlashOnChange value={ticker?.price ?? null}>
                {ticker?.price != null ? (
                  <NumberFlow
                    value={ticker.price}
                    prefix="$"
                    format={{ style: 'decimal', minimumFractionDigits: 2, maximumFractionDigits: 2 }}
                    respectMotionPreference
                  />
                ) : (
                  '—'
                )}
              </FlashOnChange>
            </div>
            {ticker?.change_pct != null && (
              <div className={`mt-3 text-headline num ${ticker.change_pct >= 0 ? 'text-bull' : 'text-bear'}`}>
                <NumberFlow
                  value={ticker.change_pct * 100}
                  format={{ style: 'decimal', minimumFractionDigits: 3, maximumFractionDigits: 3, signDisplay: 'exceptZero' }}
                  suffix="%"
                  respectMotionPreference
                />
              </div>
            )}
          </div>

          <div className="text-right space-y-1">
            <div className="text-micro uppercase tracking-wider text-ink-600">Account</div>
            <div className="num font-display text-display-sm text-gold-400">
              {portfolio?.balance != null ? (
                <NumberFlow
                  value={portfolio.balance}
                  format={{ style: 'decimal', maximumFractionDigits: 0 }}
                  respectMotionPreference
                />
              ) : (
                '—'
              )}{' '}
              <span className="text-headline opacity-60">{portfolio?.currency}</span>
            </div>
            <div className={`text-body num ${(portfolio?.pnl ?? 0) >= 0 ? 'text-bull' : 'text-bear'}`}>
              <NumberFlow
                value={portfolio?.pnl ?? 0}
                format={{ style: 'decimal', minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }}
                suffix=" today"
                respectMotionPreference
              />
            </div>
          </div>
        </div>
      </div>
    </motion.section>
  )
}

// ─── Ticker marquee ───────────────────────────────────────────────────
function TickerMarquee({
  ticker,
  trades,
}: {
  ticker: { price: number; change_pct?: number } | undefined
  trades: Trade[]
}) {
  const items: { label: string; value: string; tone: 'bull' | 'bear' | 'neutral' }[] = []
  if (ticker?.price != null) {
    items.push({
      label: 'XAU/USD',
      value: `$${ticker.price.toFixed(2)}`,
      tone: ticker.change_pct == null ? 'neutral' : ticker.change_pct >= 0 ? 'bull' : 'bear',
    })
  }
  if (ticker?.change_pct != null) {
    items.push({
      label: '24H',
      value: `${ticker.change_pct >= 0 ? '+' : ''}${(ticker.change_pct * 100).toFixed(3)}%`,
      tone: ticker.change_pct >= 0 ? 'bull' : 'bear',
    })
  }
  trades.forEach((t) => {
    const pnl = t.profit ?? 0
    const isWin = t.status === 'WIN' || t.status === 'PROFIT'
    const isLoss = t.status === 'LOSS' || t.status === 'LOSE'
    items.push({
      label: `${t.direction.slice(0, 1)} #${t.id ?? '—'}`,
      value: pnl !== 0 ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}` : t.status,
      tone: isWin ? 'bull' : isLoss ? 'bear' : 'neutral',
    })
  })
  if (!items.length) return null

  return (
    <div className="surface-raised relative overflow-hidden rounded-xl py-3 px-1">
      <Marquee speed="slow">
        {items.map((it, i) => (
          <div key={i} className="flex items-center gap-3 whitespace-nowrap">
            <span className="text-micro uppercase tracking-wider text-ink-600">{it.label}</span>
            <span
              className={`num text-body ${
                it.tone === 'bull' ? 'text-bull' : it.tone === 'bear' ? 'text-bear' : 'text-ink-800'
              }`}
            >
              {it.value}
            </span>
            <span className="h-4 w-px bg-white/[0.08]" />
          </div>
        ))}
      </Marquee>
    </div>
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
function TradesList({ trades, expanded = false }: { trades: Trade[]; expanded?: boolean }) {
  if (!trades.length) {
    return <div className="text-caption text-ink-600 py-8 text-center">No recent trades.</div>
  }
  const display = expanded ? trades : trades.slice(0, 10)
  return (
    <div className="flex flex-col">
      {display.map((t, i) => {
        const isWin = t.status === 'WIN' || t.status === 'PROFIT'
        const isLoss = t.status === 'LOSS' || t.status === 'LOSE'
        const isOpen = t.status === 'OPEN' || t.status === 'PROPOSED'
        const isLong = t.direction.toUpperCase().includes('LONG')
        return (
          <div
            key={t.id}
            className={`flex items-center justify-between py-3 ${
              i < display.length - 1 ? 'border-b border-white/[0.04]' : ''
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
function ScannerPanel({ insight, expanded = false }: { insight: ScanI | undefined; expanded?: boolean }) {
  if (!insight) {
    return <div className="text-caption text-ink-600 py-4">Waiting for scanner data…</div>
  }
  const rejections = insight.rejections?.top?.slice(0, expanded ? 20 : 5) ?? []
  const toxic = insight.toxic_patterns?.slice(0, expanded ? 10 : 3) ?? []
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

// ─── Macro mini ───────────────────────────────────────────────────────
function MacroMini({ macro }: { macro: MacroContext }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 h-full">
      <MacroCell label="USD/JPY z-score" value={macro.usdjpy_zscore?.toFixed(2) ?? '—'} />
      <MacroCell label="XAU·USDJPY corr" value={macro.xau_usdjpy_corr != null ? macro.xau_usdjpy_corr.toFixed(2) : '—'} />
      <MacroCell
        label="Macro regime"
        value={
          macro.macro_regime === 'zielony'
            ? 'bullish gold'
            : macro.macro_regime === 'czerwony'
            ? 'bearish gold'
            : 'neutral'
        }
        capitalize
      />
      <MacroCell label="Market" value={macro.market_regime?.replace('_', ' ') ?? '—'} capitalize />
    </div>
  )
}

function MacroCell({ label, value, capitalize }: { label: string; value: string; capitalize?: boolean }) {
  return (
    <div className="flex flex-col justify-center">
      <div className="text-micro uppercase tracking-wider text-ink-600">{label}</div>
      <div className={`mt-1 text-body num ${capitalize ? 'capitalize' : ''}`}>{value}</div>
    </div>
  )
}

// ─── Detail panes (lazy & lightweight; data-driven, no extra fetches) ─

function BalanceDetail({
  balance,
  pnl,
  pnlPct,
  currency,
}: {
  balance?: number
  pnl?: number
  pnlPct?: number
  currency?: string
}) {
  const { data: history } = useQuery({
    queryKey: ['portfolio-history'],
    queryFn: api.portfolioHistory,
    staleTime: 60_000,
  })
  const equity = history?.equity_values ?? []
  const pnlSeries = history?.pnl_values ?? []
  const startEquity = equity[0]
  const endEquity = equity[equity.length - 1]
  const peak = equity.length ? Math.max(...equity) : null
  const drawdown =
    peak != null && endEquity != null && peak > 0
      ? ((endEquity - peak) / peak) * 100
      : null

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-3 gap-6">
        <Stat
          size="md"
          label="Balance"
          numeric={balance ?? null}
          format={{ style: 'decimal', maximumFractionDigits: 2 }}
          suffix={currency ? ` ${currency}` : ''}
        />
        <Stat
          size="md"
          label="Unrealized P&L"
          numeric={pnl ?? null}
          format={{ style: 'decimal', maximumFractionDigits: 2, signDisplay: 'exceptZero' }}
        />
        <Stat
          size="md"
          label="Net %"
          numeric={pnlPct ?? null}
          format={{ minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }}
          suffix="%"
        />
      </div>

      {/* Equity curve from /api/portfolio/history (falls back to trades) */}
      <div className="rounded-xl2 border border-white/[0.06] bg-ink-50/40 p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600">Equity curve</div>
            <div className="text-caption text-ink-700 mt-0.5">
              {equity.length > 0
                ? `${equity.length} resolved trades · ${history?.timestamps[0]?.slice(0, 10)} → ${history?.timestamps.at(-1)?.slice(0, 10)}`
                : 'No resolved trades yet — curve will populate as trades close.'}
            </div>
          </div>
          {startEquity != null && endEquity != null && (
            <div className="text-right">
              <div className="text-micro uppercase tracking-wider text-ink-600">Net</div>
              <div className={`num text-headline ${endEquity >= startEquity ? 'text-bull' : 'text-bear'}`}>
                {endEquity >= startEquity ? '+' : ''}
                {(endEquity - startEquity).toFixed(2)}
              </div>
            </div>
          )}
        </div>
        <Sparkline values={equity} width={760} height={140} strokeWidth={2} ariaLabel="equity curve" />
        {drawdown != null && peak != null && (
          <div className="mt-3 flex items-center gap-6 text-caption text-ink-600">
            <span>
              peak <span className="num text-ink-800">{peak.toFixed(2)}</span>
            </span>
            <span>
              drawdown <span className={`num ${drawdown < 0 ? 'text-bear' : 'text-ink-800'}`}>{drawdown.toFixed(2)}%</span>
            </span>
            {pnlSeries.length > 0 && (
              <span>
                cum P&L <span className={`num ${pnlSeries.at(-1)! >= 0 ? 'text-bull' : 'text-bear'}`}>
                  {pnlSeries.at(-1)! >= 0 ? '+' : ''}
                  {pnlSeries.at(-1)!.toFixed(2)}
                </span>
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function WinRateDetail({ trades, wr, closed }: { trades: Trade[]; wr: number | null; closed: number }) {
  const longs = trades.filter((t) => t.direction.toUpperCase().includes('LONG'))
  const shorts = trades.filter((t) => t.direction.toUpperCase().includes('SHORT'))
  const longWins = longs.filter((t) => t.status === 'WIN' || t.status === 'PROFIT').length
  const shortWins = shorts.filter((t) => t.status === 'WIN' || t.status === 'PROFIT').length
  const longClosed = longs.filter((t) => t.status === 'WIN' || t.status === 'LOSS' || t.status === 'PROFIT' || t.status === 'LOSE').length
  const shortClosed = shorts.filter((t) => t.status === 'WIN' || t.status === 'LOSS' || t.status === 'PROFIT' || t.status === 'LOSE').length
  const longWr = longClosed ? (longWins / longClosed) * 100 : null
  const shortWr = shortClosed ? (shortWins / shortClosed) * 100 : null

  return (
    <div className="grid grid-cols-3 gap-6">
      <Stat size="md" label="All" numeric={wr} format={{ maximumFractionDigits: 1 }} suffix="%" hint={`${closed} closed`} />
      <Stat size="md" label="Long" numeric={longWr} format={{ maximumFractionDigits: 1 }} suffix="%" hint={`${longClosed} closed`} />
      <Stat size="md" label="Short" numeric={shortWr} format={{ maximumFractionDigits: 1 }} suffix="%" hint={`${shortClosed} closed`} />
    </div>
  )
}

function RecentPnlDetail({ trades, total }: { trades: Trade[]; total: number }) {
  const wins = trades.filter((t) => (t.profit ?? 0) > 0)
  const losses = trades.filter((t) => (t.profit ?? 0) < 0)
  const sumWin = wins.reduce((s, t) => s + (t.profit ?? 0), 0)
  const sumLoss = losses.reduce((s, t) => s + (t.profit ?? 0), 0)
  const avg = trades.length ? total / trades.length : 0

  return (
    <div className="grid grid-cols-4 gap-6">
      <Stat size="md" label="Total" numeric={total} format={{ maximumFractionDigits: 2, signDisplay: 'exceptZero' }} />
      <Stat size="md" label="Avg / trade" numeric={avg} format={{ maximumFractionDigits: 2, signDisplay: 'exceptZero' }} />
      <Stat size="md" label="Sum wins" numeric={sumWin} format={{ maximumFractionDigits: 2, signDisplay: 'exceptZero' }} hint={`${wins.length} trades`} />
      <Stat size="md" label="Sum losses" numeric={sumLoss} format={{ maximumFractionDigits: 2, signDisplay: 'exceptZero' }} hint={`${losses.length} trades`} />
    </div>
  )
}

function MacroDetail({ macro }: { macro: MacroContext }) {
  // Pull recent USDJPY 1h candles to draw an inline trend chart inside the
  // macro expandable. 200 hourly bars ≈ 8 trading days of context.
  const { data: usdjpy } = useQuery({
    queryKey: ['usdjpy-candles'],
    queryFn: () => api.candles('USD/JPY', '1h', 200),
    staleTime: 60_000,
  })
  const closes = (usdjpy ?? []).map((c) => c.close)
  const last = closes.length ? closes[closes.length - 1] : null
  const first = closes.length ? closes[0] : null
  const change = last != null && first != null ? ((last - first) / first) * 100 : null

  return (
    <div className="flex flex-col gap-6">
      <MacroMini macro={macro} />

      {/* USDJPY trend — primary USD-strength proxy */}
      <div className="rounded-xl2 border border-white/[0.06] bg-ink-50/40 p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-micro uppercase tracking-wider text-ink-600">USD/JPY · 1h · 200 bars</div>
            <div className="text-caption text-ink-700 mt-0.5">
              Primary USD-strength proxy. Inverse correlation with XAU (≈ −0.6 historically).
            </div>
          </div>
          {last != null && (
            <div className="text-right">
              <div className="num text-headline text-ink-900">
                <NumberFlow
                  value={last}
                  format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}
                  respectMotionPreference
                />
              </div>
              {change != null && (
                <div className={`text-caption num ${change >= 0 ? 'text-bull' : 'text-bear'}`}>
                  {change >= 0 ? '+' : ''}
                  {change.toFixed(2)}%
                </div>
              )}
            </div>
          )}
        </div>
        <Sparkline values={closes} width={760} height={120} strokeWidth={1.8} ariaLabel="USDJPY 1h" />
      </div>

      <div className="text-caption text-ink-600 leading-relaxed">
        <strong className="text-ink-800 font-medium">USD/JPY</strong> is the system's primary USD-strength proxy
        (DXY data quality is too low at intraday for TwelveData feed). Z-score above +1
        signals USD over-bought, typically <span className="text-bear">bearish</span> for gold.
        <br />
        <strong className="text-ink-800 font-medium">XAU·USDJPY correlation</strong> is the 20-bar Pearson
        coefficient — values near −0.6 confirm classical inverse relationship.
        <br />
        <strong className="text-ink-800 font-medium">Macro regime</strong> aggregates UUP / TLT / VIXY into a single
        zielony/czerwony/neutralny tag.
      </div>
    </div>
  )
}

// ─── Open positions detail — live unrealized P&L ─────────────────────
function OpenPositionsDetail() {
  const { data, isLoading } = useQuery({
    queryKey: ['open-positions'],
    queryFn: api.openPositions,
    refetchInterval: 5_000,
  })
  const positions = data?.positions ?? []
  const totalPnl = data?.total_unrealized_pnl ?? 0
  const spot = data?.current_price

  if (isLoading) return <div className="text-caption text-ink-600">Loading positions…</div>
  if (!positions.length) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-center">
        <div className="text-headline text-ink-700 mb-2">No open positions</div>
        <div className="text-caption text-ink-600 max-w-sm">
          The scanner will open the next entry when its cascade finds a setup that
          passes all filters. Use Cmd+K → <span className="font-mono">Pause scanner</span>{' '}
          to halt new entries.
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-3 gap-4">
        <Stat
          size="sm"
          label="Positions"
          numeric={positions.length}
          format={{ maximumFractionDigits: 0 }}
        />
        <Stat
          size="sm"
          label="Spot price"
          numeric={spot ?? null}
          format={{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}
          prefix="$"
        />
        <Stat
          size="sm"
          label="Unrealized P&L"
          numeric={totalPnl}
          format={{ minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }}
        />
      </div>

      <div className="flex flex-col">
        {positions.map((p, i) => {
          const isLong = p.direction.toUpperCase().includes('LONG')
          const upnl = p.unrealized_pnl ?? 0
          return (
            <div
              key={p.id}
              className={`flex items-center justify-between py-3 ${
                i < positions.length - 1 ? 'border-b border-white/[0.04]' : ''
              }`}
            >
              <div className="flex items-center gap-4 min-w-0 flex-1">
                <span className={`pill ${isLong ? 'pill-bull' : 'pill-bear'} shrink-0`}>
                  {isLong ? 'LONG' : 'SHORT'}
                </span>
                <div className="min-w-0">
                  <div className="text-body num">
                    ${p.entry.toFixed(2)} <span className="text-ink-600">→</span>{' '}
                    <span className="text-bull">${p.tp.toFixed(2)}</span>{' '}
                    <span className="text-ink-600">/</span>{' '}
                    <span className="text-bear">${p.sl.toFixed(2)}</span>
                  </div>
                  <div className="text-caption text-ink-600 num">
                    #{p.id} · lot {p.lot ?? '—'}
                    {p.timestamp && (
                      <> · {new Date(p.timestamp).toLocaleString(undefined, {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                      })}</>
                    )}
                  </div>
                </div>
              </div>
              <div className="text-right shrink-0 ml-4">
                <div className={`num text-body ${upnl >= 0 ? 'text-bull' : 'text-bear'}`}>
                  <NumberFlow
                    value={upnl}
                    format={{ minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }}
                    respectMotionPreference
                  />
                </div>
                <div className="text-micro text-ink-600 uppercase tracking-wider">unrealized</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
