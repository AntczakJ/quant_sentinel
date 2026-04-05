/**
 * pages/AgentPage.tsx — Full-height AI Agent chat
 */

import { AgentChat } from '../components/dashboard';

export default function AgentPage() {
  return (
    <div className="card" style={{ minHeight: 'calc(100vh - 160px)' }}>
      <h2 className="section-title mb-3">
        AI Agent
        {' '}
        <span className="text-xs text-green-500 font-normal ml-1">● memory</span>
      </h2>
      <AgentChat />
    </div>
  );
}


