/**
 * src/components/dashboard/ModelDriftAlert.tsx — Model drift & health monitoring
 *
 * Displays alerts when ML models show prediction drift, degraded accuracy,
 * or calibration issues. Uses /api/models/monitor endpoint.
 */

import { memo, useState } from 'react';
import { AlertTriangle, CheckCircle, Activity, ChevronDown, ChevronUp, Shield } from 'lucide-react';
import { Tooltip } from '../ui/Tooltip';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { modelMonitorAPI } from '../../api/client';

interface DriftInfo {
  psi: number;
  status: string;
  baseline_mean?: number;
  current_mean?: number;
}

interface AccuracyInfo {
  rolling_accuracy: number;
  window?: number;
  trend?: string;
}

interface MonitorData {
  drift: Record<string, DriftInfo>;
  accuracy: Record<string, number | AccuracyInfo>;
  calibration: Record<string, unknown>;
  alerts: string[];
  healthy: boolean;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; icon: typeof AlertTriangle }> = {
  ok:    { bg: 'bg-accent-green/8 border-accent-green/20',  text: 'text-accent-green', icon: CheckCircle },
  warn:  { bg: 'bg-accent-orange/8 border-accent-orange/20', text: 'text-accent-orange', icon: AlertTriangle },
  alert: { bg: 'bg-accent-red/10 border-accent-red/25',     text: 'text-accent-red',    icon: AlertTriangle },
};

const MODEL_COLORS: Record<string, string> = {
  xgb: 'text-accent-orange', xgboost: 'text-accent-orange',
  lstm: 'text-accent-purple',
  dqn: 'text-accent-blue', rl: 'text-accent-blue',
  ensemble: 'text-accent-cyan',
};

function getModelColor(name: string): string {
  const lower = name.toLowerCase();
  for (const [key, color] of Object.entries(MODEL_COLORS)) {
    if (lower.includes(key)) {return color;}
  }
  return 'text-th-secondary';
}

/** Normalize accuracy from API — can be a flat number or AccuracyInfo object */
function normalizeAccuracy(raw: number | AccuracyInfo | undefined): AccuracyInfo | undefined {
  if (raw === undefined) {return undefined;}
  if (typeof raw === 'number') {return { rolling_accuracy: raw };}
  return raw;
}

/** Single model drift row */
function DriftRow({ name, drift, accuracy: rawAccuracy }: {
  name: string; drift?: DriftInfo; accuracy?: number | AccuracyInfo;
}) {
  const accuracy = normalizeAccuracy(rawAccuracy);
  const status = drift?.status ?? 'ok';
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.ok;
  const StatusIcon = style.icon;
  const modelColor = getModelColor(name);

  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${style.bg}`}>
      {/* Status icon */}
      <StatusIcon size={12} className={style.text} />

      {/* Model name */}
      <span className={`text-xs font-bold w-16 ${modelColor}`}>
        {name.toUpperCase()}
      </span>

      {/* PSI */}
      {drift && (
        <div className="flex items-center gap-1">
          <Tooltip content="Population Stability Index — mierzy dryft predykcji. PSI < 0.1 = OK, > 0.25 = alert">
            <span className="text-[9px] text-th-muted cursor-help">PSI:</span>
          </Tooltip>
          <span className={`text-[10px] font-mono font-bold ${style.text}`}>
            {drift.psi.toFixed(3)}
          </span>
        </div>
      )}

      {/* Rolling accuracy */}
      {accuracy && (
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-[9px] text-th-muted">Acc:</span>
          <span className={`text-[10px] font-mono font-bold ${
            accuracy.rolling_accuracy >= 0.55 ? 'text-accent-green'
              : accuracy.rolling_accuracy >= 0.45 ? 'text-accent-orange'
              : 'text-accent-red'
          }`}>
            {(accuracy.rolling_accuracy * 100).toFixed(1)}%
          </span>
          {/* Trend arrow (if available) */}
          {accuracy.trend && (
            <span className={`text-[9px] ${
              accuracy.trend === 'improving' ? 'text-accent-green' :
              accuracy.trend === 'degrading' ? 'text-accent-red' : 'text-th-dim'
            }`}>
              {accuracy.trend === 'improving' ? '↑' : accuracy.trend === 'degrading' ? '↓' : '→'}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export const ModelDriftAlert = memo(function ModelDriftAlert() {
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading } = usePollingQuery<MonitorData>(
    'model-monitor',
    () => modelMonitorAPI.getMonitor(),
    120_000, // 2 min
  );

  if (isLoading && !data) {
    return null; // Don't show anything while loading — non-intrusive
  }

  if (!data) {return null;}

  const hasAlerts = data.alerts.length > 0;
  const modelNames = [...new Set([...Object.keys(data.drift), ...Object.keys(data.accuracy)])]
    .filter(k => k !== 'n'); // exclude sample size key from accuracy response

  return (
    <div className="space-y-2">
      {/* ── Alert banner (always visible) ─────────────────────── */}
      <button
        onClick={() => setExpanded(v => !v)}
        className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg border transition-all ${
          hasAlerts
            ? 'bg-accent-red/8 border-accent-red/25 hover:bg-accent-red/12'
            : 'bg-accent-green/6 border-accent-green/15 hover:bg-accent-green/10'
        }`}
      >
        {hasAlerts ? (
          <AlertTriangle size={14} className="text-accent-red" />
        ) : (
          <Shield size={14} className="text-accent-green" />
        )}
        <div className="flex-1 text-left">
          <div className={`text-xs font-bold ${hasAlerts ? 'text-accent-red' : 'text-accent-green'}`}>
            {hasAlerts ? `${data.alerts.length} Model Alert${data.alerts.length > 1 ? 's' : ''}` : 'Models Healthy'}
          </div>
          {hasAlerts && (
            <div className="text-[10px] text-th-muted mt-0.5 truncate">
              {data.alerts[0]}
            </div>
          )}
        </div>
        <Activity size={10} className="text-th-muted" />
        {expanded ? <ChevronUp size={12} className="text-th-muted" /> : <ChevronDown size={12} className="text-th-muted" />}
      </button>

      {/* ── Expanded details ──────────────────────────────────── */}
      {expanded && (
        <div className="space-y-1.5">
          {/* Alert messages */}
          {hasAlerts && (
            <div className="space-y-1">
              {data.alerts.map((alert, i) => (
                <div key={i} className="flex items-start gap-2 px-3 py-1.5 bg-accent-red/6 rounded text-[10px] text-accent-red border border-accent-red/15">
                  <AlertTriangle size={10} className="mt-0.5 flex-shrink-0" />
                  <span>{alert}</span>
                </div>
              ))}
            </div>
          )}

          {/* Per-model breakdown */}
          <div className="space-y-1">
            {modelNames.map(name => (
              <DriftRow
                key={name}
                name={name}
                drift={data.drift[name]}
                accuracy={data.accuracy[name]}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
});
