import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Card } from '@/components/Card'

export default function Models() {
  const { data } = useQuery({ queryKey: ['models'], queryFn: api.models, refetchInterval: 60_000 })
  const models = data?.models ?? []

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">Models</h1>
        <p className="text-body text-ink-600 mt-2">
          Trained ensemble voters. Score is hold-out MSE on triple-barrier R-multiple targets — lower is better.
        </p>
      </header>

      {models.length === 0 ? (
        <Card variant="flat" className="p-12 text-center text-ink-600">
          No models loaded. Run <span className="font-mono text-ink-800">python scripts/train_v2.py</span> to train.
        </Card>
      ) : (
        <div className="grid lg:grid-cols-2 gap-4">
          {models.map((m, i) => (
            <Card key={m.name} variant="interactive" delay={i * 0.05} className="p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className={`pill ${
                        m.direction === 'long' ? 'pill-bull' : m.direction === 'short' ? 'pill-bear' : 'pill'
                      }`}
                    >
                      {m.direction}
                    </span>
                    {m.name.includes('xgb') && <span className="pill">XGB</span>}
                    {m.name.includes('lstm') && <span className="pill">LSTM</span>}
                  </div>
                  <div className="text-title font-display truncate">{m.name}</div>
                  <div className="text-caption text-ink-600 mt-1">
                    Trained {new Date(m.trained_at).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-micro uppercase tracking-wider text-ink-600">MSE</div>
                  <div className="num text-headline font-display">{m.score?.toFixed(2) ?? '—'}</div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
