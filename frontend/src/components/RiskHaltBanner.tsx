/**
 * RiskHaltBanner.tsx — prominent banner shown at top of Dashboard when
 * scanner is paused or risk-halted. Displays the REASON so operator
 * understands why no trades are firing.
 *
 * 2026-05-04: shipped per 6-agent frontend audit (ROI 9.5/10, S effort).
 * Previously paused state showed only generic "pause/resume" buttons —
 * operator confusion when no trades fired for hours.
 */
import { useEffect, useState } from 'react'
import { api } from '../api/client'

interface ScannerStatus {
  paused: boolean
  reason: string | null
  since: string | null
}

export function RiskHaltBanner() {
  const [status, setStatus] = useState<ScannerStatus | null>(null)

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const s = await api.scannerStatus()
        setStatus(s)
      } catch {
        // Silently ignore — banner just won't show.
      }
    }
    fetchStatus()
    const id = setInterval(fetchStatus, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!status?.paused) return null

  // Compute "since" duration
  let sinceLabel = ''
  if (status.since) {
    try {
      const ms = Date.now() - new Date(status.since).getTime()
      const min = Math.floor(ms / 60_000)
      if (min < 60) sinceLabel = `${min}m`
      else sinceLabel = `${Math.floor(min / 60)}h ${min % 60}m`
    } catch {
      // ignore
    }
  }

  return (
    <div className="bg-bear/10 border border-bear/40 rounded-2xl px-5 py-4 mb-5 flex items-start gap-4">
      <div className="text-2xl">⛔</div>
      <div className="flex-1">
        <div className="text-body font-semibold text-bear mb-1">
          Scanner paused
          {sinceLabel ? <span className="text-ink-600 font-normal"> · {sinceLabel} ago</span> : null}
        </div>
        <div className="text-caption text-ink-700">
          {status.reason ?? 'No reason recorded — check scanner logs.'}
        </div>
        <div className="text-micro text-ink-600 mt-2">
          To resume, delete <code>data/SCANNER_PAUSED</code> file or use Settings → Scanner control.
        </div>
      </div>
    </div>
  )
}
