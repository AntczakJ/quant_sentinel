import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Card } from '@/components/Card'

export default function Settings() {
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health })
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: api.portfolio })

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">Settings</h1>
        <p className="text-body text-ink-600 mt-2">System configuration and live state.</p>
      </header>

      <div className="grid lg:grid-cols-2 gap-4">
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
