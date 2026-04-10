/**
 * AgentChat.tsx — Quant Sentinel Gold Trader Agent chat interface.
 */

import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Wrench, RefreshCw, Trash2, AlertTriangle } from 'lucide-react';
import { agentAPI } from '../../api/client';
import { useTradingStore } from '../../store/tradingStore';
import { MarkdownText } from '../ui/MarkdownText';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: Array<{ name: string; args: Record<string, unknown> }>;
  timestamp: Date;
}

const THREAD_STORAGE_KEY = 'qs_agent_thread_id';

const QUICK_ACTIONS = [
  { label: 'Analiza M15', message: 'Przeanalizuj XAU/USD na M15 i ocen aktualny setup SMC.' },
  { label: 'Sygnal', message: 'Wygeneruj sygnal tradingowy na M15 z kapitalem 10000 USD.' },
  { label: 'Newsy', message: 'Pobierz najnowsze newsy i zinterpretuj ich wplyw na zloto.' },
  { label: 'Kalendarz', message: 'Sprawdz nadchodzace wydarzenia makro USD (NFP, CPI, FOMC).' },
  { label: 'Portfolio', message: 'Pokaz statystyki portfela i ostatnie wyniki.' },
];

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        'Czesc! Jestem **Quant Sentinel Gold Trader** — Twoj asystent tradingowy XAU/USD z pamiecia.\n\n' +
        'Mam dostep do:\n' +
        '- Analizy SMC (Liquidity Grab, MSS, FVG, Order Blocks)\n' +
        '- Generowania sygnalow z entry/SL/TP\n' +
        '- Newsow i kalendarza ekonomicznego\n' +
        '- Statystyk portfela\n\n' +
        'Pamietam nasza rozmowe — mozesz pytac o kontekst poprzednich analiz!',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingTime, setLoadingTime] = useState(0);
  const [threadId, setThreadId] = useState<string | undefined>(
    () => localStorage.getItem(THREAD_STORAGE_KEY) ?? undefined
  );
  const [agentAvailable, setAgentAvailable] = useState<boolean | null>(null);
  const apiConnected = useTradingStore((s) => s.apiConnected);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isAbortedRef = useRef(false);

  useEffect(() => {
    if (!apiConnected) { setAgentAvailable(false); return; }
    void agentAPI.getInfo().then((info) => {
      setAgentAvailable(info.available as boolean);
    }).catch(() => setAgentAvailable(false));
  }, [apiConnected]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) {return;}

    const userMessage: Message = {
      role: 'user',
      content: text.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setLoadingTime(0);
    isAbortedRef.current = false;

    timerRef.current = setInterval(() => {
      setLoadingTime((t) => t + 1);
    }, 1000);

    const timeoutId = setTimeout(() => {
      if (!isAbortedRef.current) {
        isAbortedRef.current = true;
        if (timerRef.current) {clearInterval(timerRef.current);}
        setLoading(false);
        setLoadingTime(0);
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: '**Przekroczono czas oczekiwania** (120s)\n\nAgent prawdopodobnie czeka na dane z zewnetrznego API. Sprobuj ponownie za chwile.',
            timestamp: new Date(),
          },
        ]);
      }
    }, 120000);

    try {
      const result = await agentAPI.chat(text.trim(), threadId);
      clearTimeout(timeoutId);
      if (timerRef.current) {clearInterval(timerRef.current);}

      if (isAbortedRef.current) {return;}
      isAbortedRef.current = true;

      if (result.thread_id) {
        setThreadId(result.thread_id);
        localStorage.setItem(THREAD_STORAGE_KEY, result.thread_id);
      }

      const assistantMessage: Message = {
        role: 'assistant',
        content: result.response,
        toolCalls: result.tool_calls,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      clearTimeout(timeoutId);
      if (timerRef.current) {clearInterval(timerRef.current);}
      if (!isAbortedRef.current) {
        isAbortedRef.current = true;
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: '**Blad polaczenia z agentem.**\n\nSprawdz czy API jest uruchomione (`python api/main.py`).',
            timestamp: new Date(),
          },
        ]);
      }
    } finally {
      setLoading(false);
      setLoadingTime(0);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  };

  const resetThread = () => {
    localStorage.removeItem(THREAD_STORAGE_KEY);
    setThreadId(undefined);
    setMessages([
      {
        role: 'assistant',
        content: 'Pamiec rozmowy wyczyszczona. Zaczynam od nowa!',
        timestamp: new Date(),
      },
    ]);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-accent-green" />
          <span className="text-xs text-th-secondary font-semibold uppercase tracking-wider">
            AI Agent
          </span>
          {!agentAvailable && (
            <span className="text-xs text-accent-red bg-accent-red/15 px-2 py-0.5 rounded">
              Offline
            </span>
          )}
          {agentAvailable && threadId && (
            <span className="text-xs text-accent-green bg-accent-green/15 px-2 py-0.5 rounded">
              Pamiec aktywna
            </span>
          )}
        </div>
        <button
          onClick={resetThread}
          title="Wyczysc historie rozmowy"
          className="text-th-muted hover:text-accent-red transition-colors"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* Quick Action Buttons */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            onClick={() => void sendMessage(action.message)}
            disabled={loading}
            className="text-xs px-2 py-1 bg-dark-secondary hover:bg-th-hover text-th-secondary rounded-md transition-all disabled:opacity-40 border border-dark-secondary hover:border-accent-green/30"
          >
            {action.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 mb-3 min-h-0 max-h-[60vh] pr-1">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
            {/* Avatar */}
            <div
              className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${
                msg.role === 'user'
                  ? 'bg-accent-green/20 text-accent-green'
                  : 'bg-accent-purple/20 text-accent-purple'
              }`}
            >
              {msg.role === 'user' ? <User size={12} /> : <Bot size={12} />}
            </div>

            {/* Bubble */}
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-accent-green/10 border border-accent-green/15 text-th'
                  : 'bg-dark-bg border border-dark-secondary text-th-secondary'
              }`}
            >
              <MarkdownText text={msg.content} />

              {/* Tool calls badge */}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-dark-secondary">
                  {msg.toolCalls.map((tc, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 text-xs text-accent-blue bg-accent-blue/15 px-1.5 py-0.5 rounded"
                    >
                      <Wrench size={10} />
                      {tc.name}
                    </span>
                  ))}
                </div>
              )}

              <div className="text-xs text-th-dim mt-1">
                {msg.timestamp.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          </div>
        ))}

        {/* Loading indicator with timer */}
        {loading && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-accent-purple/20 flex items-center justify-center flex-shrink-0">
              <Bot size={12} className="text-accent-purple" />
            </div>
            <div className="bg-dark-secondary/50 border border-dark-secondary rounded-lg px-3 py-2">
              <div className="flex items-center gap-1.5 text-th-secondary text-xs">
                <RefreshCw size={12} className="animate-spin" />
                Agent analizuje rynek...
                <span className="text-th-dim ml-1">{loadingTime}s</span>
              </div>
              {loadingTime > 15 && (
                <div className="flex items-center gap-1 text-xs text-accent-orange/70 mt-1">
                  <AlertTriangle size={10} />
                  {loadingTime > 60 ? 'Zlozona analiza z narzedziami...' : 'Pobieranie danych rynkowych...'}
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex gap-2 mt-auto">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={!agentAvailable ? 'Agent offline — sprawdz API' : 'Zapytaj agenta... (Enter = wyslij)'}
          disabled={loading || !agentAvailable}
          rows={2}
          className="flex-1 bg-dark-secondary border border-dark-secondary focus:border-accent-green/50 rounded-lg px-3 py-2 text-sm text-th placeholder-th-dim resize-none transition-colors outline-none disabled:opacity-40"
        />
        <button
          onClick={() => void sendMessage(input)}
          disabled={loading || !input.trim() || !agentAvailable}
          className="self-end px-3 py-2 bg-accent-green hover:brightness-110 disabled:opacity-40 text-white rounded-lg transition-all"
        >
          <Send size={16} />
        </button>
      </div>

      {/* Memory info */}
      {threadId && (
        <div className="text-xs text-th-dim mt-1 text-center">
          Watek: {threadId.slice(-8)} — agent pamieta te rozmowe
        </div>
      )}
    </div>
  );
}
