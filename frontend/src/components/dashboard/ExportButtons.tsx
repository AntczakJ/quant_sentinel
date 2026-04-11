/**
 * src/components/dashboard/ExportButtons.tsx — Download buttons for trade data
 *
 * Provides CSV/JSON download for trades, equity curve, and daily report.
 */

import { memo, useState, useCallback } from 'react';
import { Download, FileText, FileJson, Loader2 } from 'lucide-react';
import { exportAPI } from '../../api/client';
import { useToast } from '../ui/Toast';

function triggerDownload(data: Blob | string, filename: string) {
  const blob = typeof data === 'string' ? new Blob([data], { type: 'text/plain' }) : data;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

interface ExportOption {
  label: string;
  icon: typeof Download;
  action: () => Promise<void>;
}

export const ExportButtons = memo(function ExportButtons() {
  const toast = useToast();
  const [loading, setLoading] = useState<string | null>(null);

  const doExport = useCallback(async (key: string, fn: () => Promise<void>) => {
    setLoading(key);
    try {
      await fn();
      toast.success(`Export ${key} complete`);
    } catch (err: unknown) {
      toast.error(`Export failed: ${err instanceof Error ? err.message : 'Error'}`);
    } finally {
      setLoading(null);
    }
  }, [toast]);

  const options: (ExportOption & { key: string })[] = [
    {
      key: 'trades-csv',
      label: 'Trades CSV',
      icon: FileText,
      action: async () => {
        const res = await exportAPI.downloadTrades('csv');
        if (!res.data) throw new Error('Empty response');
        triggerDownload(res.data as Blob, `qs-trades-${new Date().toISOString().slice(0, 10)}.csv`);
      },
    },
    {
      key: 'trades-json',
      label: 'Trades JSON',
      icon: FileJson,
      action: async () => {
        const res = await exportAPI.downloadTrades('json');
        if (!res.data) throw new Error('Empty response');
        triggerDownload(JSON.stringify(res.data, null, 2), `qs-trades-${new Date().toISOString().slice(0, 10)}.json`);
      },
    },
    {
      key: 'equity-csv',
      label: 'Equity CSV',
      icon: FileText,
      action: async () => {
        const res = await exportAPI.downloadEquity('csv');
        if (!res.data) throw new Error('Empty response');
        triggerDownload(res.data as Blob, `qs-equity-${new Date().toISOString().slice(0, 10)}.csv`);
      },
    },
    {
      key: 'daily-report',
      label: 'Daily Report',
      icon: Download,
      action: async () => {
        const data = await exportAPI.getDailyReport();
        triggerDownload(JSON.stringify(data, null, 2), `qs-daily-report-${new Date().toISOString().slice(0, 10)}.json`);
      },
    },
  ];

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <Download size={10} className="text-th-muted" />
      <span className="text-[10px] text-th-muted uppercase tracking-wider font-medium mr-1">Export</span>
      {options.map(opt => {
        const Icon = opt.icon;
        const isLoading = loading === opt.key;
        return (
          <button
            key={opt.key}
            onClick={() => void doExport(opt.key, opt.action)}
            disabled={loading !== null}
            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors bg-dark-secondary text-th-muted border border-transparent hover:text-th-secondary hover:border-accent-blue/20 disabled:opacity-40"
          >
            {isLoading ? <Loader2 size={9} className="animate-spin" /> : <Icon size={9} />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
});
