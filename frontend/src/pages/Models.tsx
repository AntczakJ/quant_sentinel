import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Card } from '@/components/Card'

export default function Models() {
  const { data: models = [] } = useQuery({ queryKey: ['models'], queryFn: api.models, refetchInterval: 60_000 })

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">Models</h1>
        <p className="text-body text-ink-600 mt-2">
          Live ensemble voters reporting from <span className="font-mono">/api/models/stats</span>.
        </p>
      </header>

      {models.length === 0 ? (
        <Card variant="flat" className="p-12 text-center text-ink-600">
          No model stats available.
        </Card>
      ) : (
        <div className="grid lg:grid-cols-2 gap-4">
          {models.map((m, i) => {
            const isLstm = m.model_name?.toLowerCase().includes('lstm')
            const isXgb = m.model_name?.toLowerCase().includes('xgb')
            const isRl = m.model_name?.toLowerCase().includes('rl') || m.model_name?.toLowerCase().includes('dqn')
            return (
              <Card key={m.model_name + i} variant="interactive" delay={i * 0.05} className="p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      {isLstm && <span className="pill">LSTM</span>}
                      {isXgb && <span className="pill">XGB</span>}
                      {isRl && <span className="pill">RL</span>}
                    </div>
                    <div className="text-title font-display truncate">{m.model_name}</div>
                    <div className="text-caption text-ink-600 mt-1">
                      Trained {m.last_training
                        ? new Date(m.last_training).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
                        : '—'}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-micro uppercase tracking-wider text-ink-600">
                      {m.win_rate != null ? 'WR' : 'Acc'}
                    </div>
                    <div className="num text-headline font-display">
                      {m.win_rate != null
                        ? `${(m.win_rate * 100).toFixed(0)}%`
                        : m.accuracy != null
                        ? `${(m.accuracy * 100).toFixed(0)}%`
                        : '—'}
                    </div>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
