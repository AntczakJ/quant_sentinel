import { useQuery } from '@tanstack/react-query'
import { useRef } from 'react'
import { motion } from 'framer-motion'
import NumberFlow from '@number-flow/react'
import { api, type ModelStat, type Trade } from '@/api/client'
import { Card } from '@/components/Card'
import { AnimatedBeam } from '@/components/AnimatedBeam'

export default function Models() {
  const { data: models = [] } = useQuery({ queryKey: ['models'], queryFn: api.models, refetchInterval: 60_000 })
  const { data: trades = [] } = useQuery({ queryKey: ['trades-recent'], queryFn: () => api.trades(10) })
  const { data: weightsResp } = useQuery({
    queryKey: ['ensemble-weights'],
    queryFn: api.ensembleWeights,
    refetchInterval: 60_000,
  })
  const norm = weightsResp?.normalized ?? {}

  // LSTM has historical key migrations (`lstm` ↔ `lstm_prev`); take the
  // larger of the two as the "active" voter share so the beam reflects
  // the model that actually carries weight today.
  const lstmW = Math.max(norm.lstm ?? 0, norm.lstm_prev ?? 0)
  const xgbW = Math.max(norm.xgb ?? 0, norm.v2_xgb ?? 0)
  const dqnW = norm.dqn ?? 0
  const beamIntensity = (w: number, acc: number | null | undefined) => {
    const a = acc ?? 0.5
    // Map (weight × accuracy) ∈ ~[0, 0.25] → beam opacity ∈ [0.25, 1.0]
    return Math.max(0.25, Math.min(1, w * a * 8))
  }

  // Recent ensemble outcome — derived from latest closed trade
  const latest = trades.find((t) =>
    ['WIN', 'LOSS', 'PROFIT', 'LOSE', 'OPEN', 'PROPOSED'].includes(t.status),
  )
  const lastDirection = latest?.direction.toUpperCase().includes('LONG') ? 'BUY' : latest?.direction ? 'SELL' : 'HOLD'
  const lastConfidence = latest && latest.profit != null && Math.abs(latest.profit) > 0
    ? Math.min(0.99, 0.5 + Math.abs(latest.profit) / 200)
    : 0.62

  // Refs for the animated beam endpoints
  const containerRef = useRef<HTMLDivElement | null>(null)
  const lstmRef = useRef<HTMLDivElement | null>(null)
  const xgbRef = useRef<HTMLDivElement | null>(null)
  const rlRef = useRef<HTMLDivElement | null>(null)
  const ensembleRef = useRef<HTMLDivElement | null>(null)
  const signalRef = useRef<HTMLDivElement | null>(null)

  const findModel = (kind: string) =>
    models.find((m) => m.model_name?.toLowerCase().includes(kind))

  const lstm = findModel('lstm')
  const xgb = findModel('xgb')
  const rl = findModel('rl') ?? findModel('dqn')

  return (
    <div className="flex flex-col gap-10">
      <header className="reveal-on-scroll">
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">Models</h1>
        <p className="text-body text-ink-600 mt-2">
          Voter ensemble — live data flow from <span className="font-mono">/api/models/stats</span>.
        </p>
      </header>

      {/* ─── Voter → ensemble → signal flow ─────────────────────────── */}
      <div
        ref={containerRef}
        className="relative rounded-xl3 p-8 lg:p-10 border border-white/[0.06] bg-ink-100/40 backdrop-blur-sm overflow-hidden min-h-[520px]"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0)',
          backgroundSize: '28px 28px',
        }}
      >
        <div className="grid grid-cols-3 gap-12 items-center relative z-10 h-full">
          {/* ─── Left: voters ─────────────────────────────────────── */}
          <div className="flex flex-col gap-5 items-stretch">
            <VoterCard ref={lstmRef} kind="LSTM" model={lstm} accent="#3b82f6" weight={lstmW} />
            <VoterCard ref={xgbRef}  kind="XGB"  model={xgb}  accent="#22c55e" weight={xgbW} />
            <VoterCard ref={rlRef}   kind="RL"   model={rl}   accent="#d4af37" weight={dqnW} />
          </div>

          {/* ─── Center: ensemble ─────────────────────────────────── */}
          <div className="flex justify-center">
            <motion.div
              ref={ensembleRef}
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.6, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
              className="relative w-44 h-44 rounded-full
                         bg-gradient-to-br from-ink-100 to-ink-200
                         border border-gold-500/30
                         flex flex-col items-center justify-center
                         animate-pulse-glow"
            >
              <div className="absolute inset-1 rounded-full border border-white/[0.04]" />
              <div className="text-micro uppercase tracking-wider text-ink-600 z-10">Ensemble</div>
              <div className="num text-display-sm font-display text-gold-400 z-10 mt-1">
                <NumberFlow
                  value={lastConfidence * 100}
                  format={{ maximumFractionDigits: 0 }}
                  suffix="%"
                  respectMotionPreference
                />
              </div>
              <div className="text-micro text-ink-600 mt-1 z-10">confidence</div>
            </motion.div>
          </div>

          {/* ─── Right: signal output ─────────────────────────────── */}
          <div className="flex justify-end">
            <motion.div
              ref={signalRef}
              initial={{ scale: 0.92, opacity: 0, x: 20 }}
              animate={{ scale: 1, opacity: 1, x: 0 }}
              transition={{ duration: 0.6, delay: 0.4 }}
              className={`min-w-[200px] rounded-xl2 p-5 border backdrop-blur-sm ${
                lastDirection === 'BUY'
                  ? 'border-bull/30 bg-bull/[0.06] shadow-glow-bull'
                  : lastDirection === 'SELL'
                  ? 'border-bear/30 bg-bear/[0.06] shadow-glow-bear'
                  : 'border-white/[0.08] bg-white/[0.02]'
              }`}
            >
              <div className="text-micro uppercase tracking-wider text-ink-600">Signal</div>
              <div
                className={`text-display-sm font-display mt-2 ${
                  lastDirection === 'BUY' ? 'text-bull' : lastDirection === 'SELL' ? 'text-bear' : 'text-ink-700'
                }`}
              >
                {lastDirection}
              </div>
              <div className="text-caption text-ink-600 mt-2">
                Latest closed trade · {latest?.timeframe ?? '—'}
              </div>
              <div className="text-caption text-ink-700 mt-1 num">
                {latest?.profit != null
                  ? `${latest.profit >= 0 ? '+' : ''}${latest.profit.toFixed(2)}`
                  : '—'}
              </div>
            </motion.div>
          </div>
        </div>

        {/* ─── Beams ──────────────────────────────────────────────── */}
        <AnimatedBeam
          containerRef={containerRef}
          fromRef={lstmRef}
          toRef={ensembleRef}
          curvature={-30}
          duration={3.6}
          delay={0.3}
          gradientStartColor="#3b82f6"
          gradientStopColor="#d4af37"
          intensity={beamIntensity(lstmW, lstm?.accuracy)}
        />
        <AnimatedBeam
          containerRef={containerRef}
          fromRef={xgbRef}
          toRef={ensembleRef}
          curvature={0}
          duration={3.2}
          delay={0.5}
          gradientStartColor="#22c55e"
          gradientStopColor="#d4af37"
          intensity={beamIntensity(xgbW, xgb?.accuracy)}
        />
        <AnimatedBeam
          containerRef={containerRef}
          fromRef={rlRef}
          toRef={ensembleRef}
          curvature={30}
          duration={3.8}
          delay={0.7}
          gradientStartColor="#d4af37"
          gradientStopColor="#d4af37"
          intensity={beamIntensity(dqnW, rl?.win_rate ?? rl?.accuracy)}
        />
        <AnimatedBeam
          containerRef={containerRef}
          fromRef={ensembleRef}
          toRef={signalRef}
          curvature={0}
          duration={2.4}
          delay={0.9}
          pathWidth={3}
          gradientStartColor="#d4af37"
          gradientStopColor={
            lastDirection === 'BUY' ? '#22c55e' : lastDirection === 'SELL' ? '#ef4444' : '#a1a1aa'
          }
        />
      </div>

      {/* ─── Detailed model stats grid ──────────────────────────────── */}
      <section className="reveal-on-scroll">
        <h2 className="text-title font-display mb-4">Voter detail</h2>
        {models.length === 0 ? (
          <Card variant="flat" className="p-12 text-center text-ink-600">
            No model stats available.
          </Card>
        ) : (
          <div className="grid lg:grid-cols-3 gap-4">
            {models.map((m, i) => {
              const acc = m.win_rate != null
                ? m.win_rate * 100
                : m.accuracy != null
                ? m.accuracy * 100
                : null
              return (
                <Card key={m.model_name + i} variant="interactive" delay={i * 0.05} className="p-6">
                  <div className="text-micro uppercase tracking-wider text-ink-600">
                    {m.win_rate != null ? 'Win rate' : 'Accuracy'}
                  </div>
                  <div className="num text-display-sm font-display mt-1 text-ink-900">
                    {acc != null ? (
                      <NumberFlow
                        value={acc}
                        format={{ maximumFractionDigits: 0 }}
                        suffix="%"
                        respectMotionPreference
                      />
                    ) : (
                      '—'
                    )}
                  </div>
                  <div className="mt-3 text-body text-ink-800 truncate">{m.model_name}</div>
                  <div className="text-caption text-ink-600 mt-1">
                    Trained {m.last_training
                      ? new Date(m.last_training).toLocaleString(undefined, { month: 'short', day: 'numeric' })
                      : '—'}
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

// ─── Voter card (forwardRef so AnimatedBeam can target it) ────────────
import { forwardRef } from 'react'

interface VoterCardProps {
  kind: 'LSTM' | 'XGB' | 'RL'
  model: ModelStat | undefined
  accent: string
  /** Normalized voter weight (0..1) from `dynamic_params`. */
  weight: number
}

const VoterCard = forwardRef<HTMLDivElement, VoterCardProps>(function VoterCard(
  { kind, model, accent, weight },
  ref,
) {
  const acc = model?.win_rate != null
    ? model.win_rate * 100
    : model?.accuracy != null
    ? model.accuracy * 100
    : null
  const weightPct = Math.round(weight * 100)
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, delay: kind === 'LSTM' ? 0 : kind === 'XGB' ? 0.1 : 0.2 }}
      className="rounded-xl2 p-4 bg-ink-100 border border-white/[0.06] shadow-soft
                 transition-all hover:border-white/15 hover:shadow-lift"
      style={{ borderLeft: `2px solid ${accent}` }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-micro uppercase tracking-wider text-ink-600">{kind}</div>
          <div className="text-body text-ink-900 font-medium truncate max-w-[140px]">
            {model?.model_name ?? '—'}
          </div>
          <div className="text-micro text-ink-600 mt-1">
            weight{' '}
            <span className="num text-ink-800">
              <NumberFlow value={weightPct} format={{ maximumFractionDigits: 0 }} suffix="%" respectMotionPreference />
            </span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-micro uppercase text-ink-600">{model?.win_rate != null ? 'WR' : 'Acc'}</div>
          <div className="num text-headline font-display">
            {acc != null ? (
              <NumberFlow value={acc} format={{ maximumFractionDigits: 0 }} suffix="%" respectMotionPreference />
            ) : (
              '—'
            )}
          </div>
        </div>
      </div>
      {/* Weight progress bar — visual reinforcement of the beam intensity */}
      <div
        className="mt-3 h-1 rounded-full bg-white/[0.04] overflow-hidden"
        title={`Voter share: ${weightPct}%`}
      >
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${Math.min(100, weightPct * 3)}%`,
            background: accent,
            opacity: 0.75,
          }}
        />
      </div>
    </motion.div>
  )
})

// silence unused-import lint when types are needed transitively
export type { Trade }
