import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/api/client'
import { Card } from '@/components/Card'

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

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">Trades</h1>
        <p className="text-body text-ink-600">All closed and open positions, most recent first.</p>
      </header>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total', value: filtered.length, mono: true },
          { label: 'Win Rate', value: wr != null ? `${wr.toFixed(1)}%` : '—' },
          { label: 'Net P&L', value: `${total >= 0 ? '+' : ''}${total.toFixed(0)}` },
          { label: 'Closed', value: closed.length, mono: true },
        ].map((s) => (
          <Card key={s.label} variant="flat" className="p-5">
            <div className="text-micro uppercase tracking-wider text-ink-600">{s.label}</div>
            <div className={`mt-2 text-headline font-display ${s.mono ? 'num' : ''}`}>{s.value}</div>
          </Card>
        ))}
      </div>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-full text-caption capitalize transition-all ${
              filter === f
                ? 'bg-white/[0.08] text-ink-900 border border-white/15'
                : 'bg-transparent text-ink-600 border border-white/[0.06] hover:border-white/15 hover:text-ink-800'
            }`}
          >
            {f}
          </button>
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
              <th className="text-left py-4 px-2 font-medium">Pattern</th>
              <th className="text-right py-4 px-6 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
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
