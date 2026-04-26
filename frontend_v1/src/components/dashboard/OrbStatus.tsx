/**
 * OrbStatus.tsx — Compact Asia Session ORB status for the chart page.
 *
 * Shows at-a-glance whether the Asia H/L breakout voter is in its firing
 * window (07:00-09:00 UTC) and what the current signal is. When outside
 * the window, shows countdown to next London open.
 *
 * The ORB voter adds +15 to setup score when direction matches — not
 * being able to see its state was making the voter "invisible" to the
 * operator despite 90 min invested in building it.
 */

import { useEffect, useState, memo } from 'react';
import { Sunrise, Clock, TrendingUp, TrendingDown, CircleDot } from 'lucide-react';
import client from '../../api/client';

interface OrbHealth {
  status: string;
  asia?: {
    high: number;
    low: number;
    bars: number;
    start?: string;
    end?: string;
  } | null;
  window_active?: boolean;
  minutes_to_next_london_open?: number;
  ema200_filter?: number | null;
  signal?: {
    direction: 'LONG' | 'SHORT' | 'NONE';
    reason: string;
    asia_high: number | null;
    asia_low: number | null;
    current_close: number | null;
  };
  detail?: string;
}

function fmtDuration(mins: number | undefined): string {
  if (mins === undefined || mins < 0) {
    return '—';
  }
  if (mins < 60) {
    return `${mins}m`;
  }
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function OrbStatusInner() {
  const [data, setData] = useState<OrbHealth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await client.get<OrbHealth>('/health/orb');
        if (alive) {
          setData(r.data);
        }
      } catch {
        // silent — ORB status is ancillary
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    };
    void load();
    const id = window.setInterval(load, 60000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-th-muted animate-pulse">
        Loading ORB…
      </div>
    );
  }
  if (!data || data.status !== 'ok') {
    return null;
  }

  const active = !!data.window_active;
  const sig = data.signal;
  const asia = data.asia;

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 text-xs bg-dark-bg-soft rounded-lg border border-dark-secondary">
      <span className="flex items-center gap-1 text-[10px] text-th-muted uppercase tracking-wider">
        <Sunrise size={11} />
        Asia ORB
      </span>

      {asia ? (
        <div className="flex items-center gap-2">
          <span className="text-th-muted">H</span>
          <span className="font-mono text-th-primary">{asia.high.toFixed(2)}</span>
          <span className="text-th-muted">L</span>
          <span className="font-mono text-th-primary">{asia.low.toFixed(2)}</span>
          <span className="text-[10px] text-th-muted">({asia.bars} bars)</span>
        </div>
      ) : (
        <span className="text-th-muted italic">no Asia data</span>
      )}

      <span className="text-dark-secondary">|</span>

      {/* Window state */}
      <div className="flex items-center gap-1">
        <CircleDot
          size={11}
          className={active ? 'text-accent-green animate-pulse' : 'text-th-muted'}
        />
        {active ? (
          <span className="font-mono font-medium text-accent-green">ACTIVE</span>
        ) : (
          <span className="flex items-center gap-1 font-mono text-th-muted">
            <Clock size={10} />
            {fmtDuration(data.minutes_to_next_london_open)} to London open
          </span>
        )}
      </div>

      {/* Live signal when window active */}
      {active && sig && sig.direction !== 'NONE' && (
        <>
          <span className="text-dark-secondary">|</span>
          <div className="flex items-center gap-1">
            {sig.direction === 'LONG' ? (
              <TrendingUp size={12} className="text-accent-green" />
            ) : (
              <TrendingDown size={12} className="text-accent-red" />
            )}
            <span
              className={`font-mono font-semibold ${
                sig.direction === 'LONG' ? 'text-accent-green' : 'text-accent-red'
              }`}
            >
              {sig.direction}
            </span>
            <span className="text-[10px] text-th-muted">{sig.reason}</span>
          </div>
        </>
      )}
      {active && sig && sig.direction === 'NONE' && (
        <>
          <span className="text-dark-secondary">|</span>
          <span className="text-[11px] text-th-muted italic">
            no break yet ({sig.reason})
          </span>
        </>
      )}
    </div>
  );
}

export const OrbStatus = memo(OrbStatusInner);
