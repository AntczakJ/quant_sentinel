import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Trade } from '@/api/client'
import { playWin, playLoss } from '@/lib/sound'

/**
 * Headless component — watches the `trades-recent` cache and fires:
 *   - sonner toast (info / success / error) for new trades
 *   - WebAudio sound for wins/losses (gated by `qs.sound.enabled`)
 *
 * Never renders DOM. Mount once near the app root.
 */
export function TradeWatcher() {
  const { data: trades = [] } = useQuery({
    queryKey: ['trades-recent'],
    queryFn: () => api.trades(10),
    refetchInterval: 30_000,
  })
  const seenRef = useRef<Set<number> | null>(null)

  useEffect(() => {
    if (!trades.length) return
    if (seenRef.current === null) {
      // First load — populate without firing notifications for old trades
      seenRef.current = new Set(trades.map((t) => t.id))
      return
    }
    const seen = seenRef.current
    for (const t of trades) {
      if (seen.has(t.id)) continue
      seen.add(t.id)
      announce(t)
    }
  }, [trades])

  return null
}

function announce(t: Trade) {
  const isWin = t.status === 'WIN' || t.status === 'PROFIT'
  const isLoss = t.status === 'LOSS' || t.status === 'LOSE'
  const isOpen = t.status === 'OPEN' || t.status === 'PROPOSED'
  const dir = t.direction.toUpperCase().includes('LONG') ? 'LONG' : 'SHORT'
  const profit = t.profit != null
    ? `${t.profit >= 0 ? '+' : ''}${t.profit.toFixed(2)}`
    : '—'
  const title = `Trade #${t.id} ${dir}`
  const desc = `${t.timeframe ?? '—'} · ${t.pattern ?? '—'} · ${profit}`

  if (isWin) {
    playWin()
    toast.success(title, { description: desc })
  } else if (isLoss) {
    playLoss()
    toast.error(title, { description: desc })
  } else if (isOpen) {
    toast.info(`${title} opened`, { description: desc })
  }
}
