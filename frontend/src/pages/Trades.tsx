import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import NumberFlow from '@number-flow/react'
import { useAutoAnimate } from '@formkit/auto-animate/react'
import { api } from '@/api/client'
import { Card } from '@/components/Card'
import { FlashOnChange } from '@/components/FlashOnChange'
import { MagneticButton } from '@/components/MagneticButton'
import { TiltCard } from '@/components/TiltCard'
import { Spotlight } from '@/components/Spotlight'
import { GradientText } from '@/components/GradientText'
import { TextReveal } from '@/components/TextReveal'

type Filter = 'all' | 'win' | 'loss' | 'open' | 'long' | 'short'

export default function Trades() {
  const { data: trades = [] } = useQuery({
    queryKey: ['trades-all'],
    queryFn: () => api.trades(500),
    refetchInterval: 30_000,
  })
  const [filter, setFilter] = useState<Filter>('all')

  const filtered = trades.filter((t) => {
    if (filter === 'all') return true
    if (filter === 'win') return t.status === 'WIN' || t.status === 'PROFIT'
    if (filter === 'loss') return t.status === 'LOSS' || t.status === 'LOSE'
    if (filter === 'open') return t.status === 'OPEN' || t.status === 'PROPOSED'
    if (filter === 'long') return t.direction?.toUpperCase().includes('LONG')
    if (filter === 'short') return t.direction?.toUpperCase().includes('SHORT')
    return true
  })

  const closed = filtered.filter((t) => t.status === 'WIN' || t.status === 'LOSS' || t.status === 'PROFIT' || t.status === 'LOSE')
  const wins = closed.filter((t) => t.status === 'WIN' || t.status === 'PROFIT').length
  const wr = closed.length ? (wins / closed.length) * 100 : null
  const total = filtered.reduce((s, t) => s + (t.profit ?? 0), 0)

  const FILTERS: Filter[] = ['all', 'win', 'loss', 'open', 'long', 'short']
  const [animParent] = useAutoAnimate<HTMLTableSectionElement>({ duration: 220, easing: 'ease-out' })

  return (
    <div className="flex flex-col gap-8">
      <header className="reveal-on-scroll flex flex-col gap-2">
        <h1 className="text-display-sm font-display tracking-tight">
          <GradientText>
            <TextReveal text="Trades" splitBy="char" />
          </GradientText>
        </h1>
        <p className="text-body text-ink-600">
          <TextReveal text="All closed and open positions, most recent first." delay={0.18} />
        </p>
      </header>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <TiltCard className="rounded-xl">
          <Card variant="flat" className="relative overflow-hidden p-5">
            <Spotlight />
            <div className="text-micro uppercase tracking-wider text-ink-600">Total</div>
            <div className="mt-2 text-headline font-display num">
              <NumberFlow value={filtered.length} respectMotionPreference />
            </div>
          </Card>
        </TiltCard>
        <TiltCard className="rounded-xl">
          <Card variant="flat" className="relative overflow-hidden p-5">
            <Spotlight color="rgba(34,197,94,0.14)" />
            <div className="text-micro uppercase tracking-wider text-ink-600">Win Rate</div>
            <div className="mt-2 text-headline font-display num">
              {wr != null ? (
                <NumberFlow
                  value={wr}
                  format={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}
                  suffix="%"
                  respectMotionPreference
                />
              ) : (
                '—'
              )}
            </div>
          </Card>
        </TiltCard>
        <TiltCard className="rounded-xl">
          <Card variant="flat" className="relative overflow-hidden p-5">
            <Spotlight color={total >= 0 ? 'rgba(34,197,94,0.14)' : 'rgba(239,68,68,0.14)'} />
            <div className="text-micro uppercase tracking-wider text-ink-600">Net P&L</div>
            <div className={`mt-2 text-headline font-display num ${total > 0 ? 'text-bull' : total < 0 ? 'text-bear' : ''}`}>
              <FlashOnChange value={total}>
                <NumberFlow
                  value={total}
                  format={{ maximumFractionDigits: 0, signDisplay: 'exceptZero' }}
                  respectMotionPreference
                />
              </FlashOnChange>
            </div>
          </Card>
        </TiltCard>
        <TiltCard className="rounded-xl">
          <Card variant="flat" className="relative overflow-hidden p-5">
            <Spotlight color="rgba(59,130,246,0.14)" />
            <div className="text-micro uppercase tracking-wider text-ink-600">Closed</div>
            <div className="mt-2 text-headline font-display num">
              <NumberFlow value={closed.length} respectMotionPreference />
            </div>
          </Card>
        </TiltCard>
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <MagneticButton
            key={f}
            strength={0.16}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-full text-caption capitalize transition-colors ${
              filter === f
                ? 'bg-white/[0.08] text-ink-900 border border-white/15 shadow-glow-gold'
                : 'bg-transparent text-ink-600 border border-white/[0.06] hover:border-white/15 hover:text-ink-800'
            }`}
          >
            {f}
          </MagneticButton>
        ))}
      </div>

      {/* Table */}
      <Card variant="raised" className="overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-white/[0.04] text-micro uppercase tracking-wider text-ink-600">
              <th className="text-left py-4 px-6 font-medium">When</th>
              <th className="text-left py-4 px-2 font-medium">Dir</th>
              <th className="text-right py-4 px-2 font-medium">Entry</th>
              <th className="text-right py-4 px-2 font-medium">Exit</th>
              <th className="text-right py-4 px-2 font-medium">TF</th>
              <th className="text-right py-4 px-2 font-medium">P&L</th>
              <th className="text-center py-4 px-2 font-medium">Grade</th>
              <th className="text-center py-4 px-2 font-medium">v2</th>
              <th className="text-left py-4 px-2 font-medium">Pattern</th>
              <th className="text-right py-4 px-6 font-medium">Status</th>
            </tr>
          </thead>
          <tbody ref={animParent}>
            {filtered.slice(0, 200).map((t) => {
              const isLong = t.direction?.toUpperCase().includes('LONG')
              const isWin = t.status === 'WIN' || t.status === 'PROFIT'
              const isLoss = t.status === 'LOSS' || t.status === 'LOSE'
              const isOpen = t.status === 'OPEN' || t.status === 'PROPOSED'
              const exit = isWin || isLoss ? t.tp : null
              return (
                <tr key={t.id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                  <td className="py-3 px-6 text-caption text-ink-700 num">
                    {new Date(t.timestamp).toLocaleString(undefined, {
                      month: 'short',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="py-3 px-2">
                    <span className={`pill ${isLong ? 'pill-bull' : 'pill-bear'}`}>
                      {isLong ? 'L' : 'S'}
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right num text-body">
                    {t.entry != null ? `$${t.entry.toFixed(2)}` : '—'}
                  </td>
                  <td className="py-3 px-2 text-right num text-caption text-ink-600">
                    {exit != null ? `$${exit.toFixed(2)}` : '—'}
                  </td>
                  <td className="py-3 px-2 text-right num text-caption text-ink-700">
                    {t.timeframe || '—'}
                  </td>
                  <td
                    className={`py-3 px-2 text-right num text-body ${
                      isWin ? 'text-bull' : isLoss ? 'text-bear' : 'text-ink-700'
                    }`}
                  >
                    {t.profit != null
                      ? `${t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}`
                      : '—'}
                  </td>
                  <td className="py-3 px-2 text-center">
                    {t.setup_grade ? (
                      <span
                        className={`text-micro font-medium px-2 py-0.5 rounded ${
                          t.setup_grade === 'A+' ? 'bg-bull/30 text-bull' :
                          t.setup_grade === 'A' ? 'bg-bull/15 text-bull' :
                          t.setup_grade === 'B' ? 'bg-amber-500/15 text-amber-500' :
                          'bg-ink-200 text-ink-600'
                        }`}
                      >
                        {t.setup_grade}
                      </span>
                    ) : '—'}
                  </td>
                  <td className="py-3 px-2 text-center">
                    {(() => {
                      try {
                        const f = t.factors ? JSON.parse(t.factors) : {}
                        const v2 = f.v2_score_high ? 'H' : f.v2_score_mid ? 'M' : f.v2_score_low ? 'L' : null
                        if (!v2) return <span className="text-ink-600">—</span>
                        return (
                          <span
                            className={`text-micro font-mono px-2 py-0.5 rounded ${
                              v2 === 'H' ? 'bg-bull/20 text-bull' :
                              v2 === 'M' ? 'bg-amber-500/15 text-amber-500' :
                              'bg-bear/15 text-bear'
                            }`}
                            title={`confluence_v2 score bucket: ${v2 === 'H' ? '70+' : v2 === 'M' ? '50-69' : '30-49'}`}
                          >
                            {v2}
                          </span>
                        )
                      } catch {
                        return <span className="text-ink-600">—</span>
                      }
                    })()}
                  </td>
                  <td className="py-3 px-2 text-caption text-ink-600 truncate max-w-[160px]">
                    {t.pattern || '—'}
                  </td>
                  <td className="py-3 px-6 text-right">
                    <span
                      className={`text-micro uppercase tracking-wider ${
                        isWin ? 'text-bull' : isLoss ? 'text-bear' : isOpen ? 'text-info' : 'text-ink-600'
                      }`}
                    >
                      {t.status}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="text-center py-16 text-caption text-ink-600">No trades match this filter.</div>
        )}
      </Card>
    </div>
  )
}
