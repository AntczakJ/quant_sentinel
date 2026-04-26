/**
 * pages/AgentPage.tsx — Full-height AI Agent chat.
 *
 * Chat consumes the page; the PageHeader sits above it with a status eyebrow
 * that hints at context-memory being active.
 */

import { Sparkles } from 'lucide-react';
import { AgentChat } from '../components/dashboard';
import { PageHeader } from '../components/ui';

export default function AgentPage() {
  return (
    <div className="max-w-[1600px] mx-auto">
      <PageHeader
        eyebrow={
          <span className="inline-flex items-center gap-1.5">
            <Sparkles size={10} className="text-accent-green" />
            Memory active
          </span>
        }
        title="AI Agent"
        subtitle="Conversational interface with full access to signals, positions, and backtest tools."
      />
      <div className="card" style={{ minHeight: 'calc(100vh - 220px)' }}>
        <AgentChat />
      </div>
    </div>
  );
}


