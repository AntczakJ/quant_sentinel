/**
 * FeatureFlagsPanel.tsx — operator view of all active feature flags +
 * dynamic params controlling system behavior.
 *
 * 2026-05-04: shipped per 6-agent frontend audit. Previously flags were
 * scattered across .env + dynamic_params with no single inspection tool.
 *
 * Read-only display — actual mutation requires SSH or API auth.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export function FeatureFlagsPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['flags'],
    queryFn: api.flags,
    refetchInterval: 60_000,
  })

  if (isLoading) {
    return <div className="text-caption text-ink-600">Loading feature flags…</div>
  }
  if (isError || !data) {
    return <div className="text-caption text-bear">Could not load /api/flags.</div>
  }

  // Quick-glance section
  const today = data.session_2026_05_04_flags
  const indicators: Array<{ label: string; on: boolean; note?: string }> = [
    { label: 'Phase V2 routing', on: today.regime_v2_active },
    { label: 'Toxic pair block (choch+ob_count)', on: today.toxic_pair_filter_active },
    { label: 'LLM news sentiment', on: today.llm_news_active },
    { label: 'Calibration disabled', on: today.calibration_disabled, note: today.calibration_disabled ? 'expected' : 'unexpected!' },
    { label: 'Trailing disabled', on: today.trailing_disabled, note: today.trailing_disabled ? 'expected' : 'unexpected!' },
  ]

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">Quick state</div>
        <div className="flex flex-col gap-2">
          {indicators.map((i, idx) => (
            <div key={idx} className="flex items-center justify-between text-caption">
              <span className="text-ink-700">{i.label}</span>
              <span className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded font-medium text-[11px] ${
                    i.on
                      ? 'bg-bull/20 text-bull'
                      : 'bg-ink-200 text-ink-600'
                  }`}
                >
                  {i.on ? 'ON' : 'OFF'}
                </span>
                {i.note && (
                  <span className="text-micro text-ink-600">{i.note}</span>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">
          MAX_LOT_CAP
        </div>
        <div className="text-body num text-ink-800">
          {today.max_lot_cap.toFixed(3)} lot
        </div>
      </div>

      <div>
        <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">
          Dynamic params (active)
        </div>
        <div className="flex flex-col gap-1.5 text-caption">
          {Object.entries(data.dynamic_params)
            .filter(([, v]) => v !== '(unset)' && v !== null)
            .slice(0, 12)
            .map(([k, v]) => (
              <div key={k} className="flex items-center justify-between">
                <span className="text-ink-600 truncate mr-3">{k}</span>
                <span className="num text-ink-800 shrink-0">
                  {typeof v === 'number' ? v.toFixed(3) : String(v)}
                </span>
              </div>
            ))}
        </div>
      </div>

      <div>
        <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">
          Env flags (set)
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(data.env_flags)
            .filter(([, v]) => v && v !== '(unset)')
            .map(([k, v]) => (
              <span
                key={k}
                className="text-micro bg-ink-200 text-ink-700 px-2 py-0.5 rounded"
                title={`${k}=${v}`}
              >
                {k}
              </span>
            ))}
        </div>
      </div>
    </div>
  )
}
