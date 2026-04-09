/**
 * AgentChat.tsx — Quant Sentinel Gold Trader Agent chat interface.
 * Komunikuje się z /api/agent/chat i utrzymuje thread_id w localStorage
 * żeby agent pamiętał rozmowę między odświeżeniami strony.
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
  { label: '📊 Analiza M15', message: 'Przeanalizuj XAU/USD na M15 i oceń aktualny setup SMC.' },
  { label: '🎯 Sygnał', message: 'Wygeneruj sygnał tradingowy na M15 z kapitałem 10000 USD.' },
  { label: '📰 Newsy', message: 'Pobierz najnowsze newsy i zinterpretuj ich wpływ na złoto.' },
  { label: '📅 Kalendarz', message: 'Sprawdź nadchodzące wydarzenia makro USD (NFP, CPI, FOMC).' },
  { label: '📈 Portfolio', message: 'Pokaż statystyki portfela i ostatnie wyniki.' },
];

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        'Cześć! Jestem **Quant Sentinel Gold Trader** — Twój asystent tradingowy XAU/USD z pamięcią.\n\n' +
        'Mam dostęp do:\n' +
        '- Analizy SMC (Liquidity Grab, MSS, FVG, Order Blocks)\n' +
        '- Generowania sygnałów z entry/SL/TP\n' +
        '- Newsów i kalendarza ekonomicznego\n' +
        '- Statystyk portfela\n\n' +
        'Pamiętam naszą rozmowę — możesz pytać o kontekst poprzednich analiz!',
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
  const isAbortedRef = useRef(false);   // prevents double-message race condition

  // Sprawdź czy agent jest dostępny — only when API is up
  useEffect(() => {
    if (!apiConnected) { setAgentAvailable(false); return; }
    void agentAPI.getInfo().then((info) => {
      setAgentAvailable(info.available as boolean);
    }).catch(() => setAgentAvailable(false));
  }, [apiConnected]);

  // Auto-scroll do ostatniej wiadomości
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

    // Timer — pokazuje ile sekund agent pracuje
    timerRef.current = setInterval(() => {
      setLoadingTime((t) => t + 1);
    }, 1000);

    // Timeout 120s — jeśli agent nie odpowie, pokaż błąd
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
            content: '⏱️ **Przekroczono czas oczekiwania** (120s)\n\nAgent prawdopodobnie czeka na dane z zewnętrznego API. Spróbuj ponownie za chwilę.',
            timestamp: new Date(),
          },
        ]);
      }
    }, 120000);

    try {
      const result = await agentAPI.chat(text.trim(), threadId);
      clearTimeout(timeoutId);
      if (timerRef.current) {clearInterval(timerRef.current);}

      // If timeout already fired and set isAborted, discard late response
      if (isAbortedRef.current) {return;}
      isAbortedRef.current = true; // mark as handled

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
            content: '❌ **Błąd połączenia z agentem.**\n\nSprawdź czy API jest uruchomione (`python api/main.py`).',
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
        content: '🔄 Pamięć rozmowy wyczyszczona. Zaczynam od nowa!',
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
          <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">
            AI Agent
          </span>
          {!agentAvailable && (
            <span className="text-xs text-accent-red bg-red-900/20 px-2 py-0.5 rounded">
              Offline
            </span>
          )}
          {agentAvailable && threadId && (
            <span className="text-xs text-accent-green bg-green-900/20 px-2 py-0.5 rounded">
              Pamięć aktywna
            </span>
          )}
        </div>
        <button
          onClick={resetThread}
          title="Wyczyść historię rozmowy"
          className="text-gray-500 hover:text-accent-red transition-colors"
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
            className="text-xs px-2 py-1 bg-dark-secondary hover:bg-dark-secondary/70 text-gray-300 rounded-md transition-all disabled:opacity-40 border border-dark-secondary hover:border-accent-green/30"
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
                  ? 'bg-green-950/15 border border-green-600/15 text-gray-200'
                  : 'bg-dark-bg border border-dark-secondary text-gray-300'
              }`}
            >
              <MarkdownText text={msg.content} />

              {/* Tool calls badge */}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-dark-secondary">
                  {msg.toolCalls.map((tc, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 text-xs text-accent-blue bg-blue-900/20 px-1.5 py-0.5 rounded"
                    >
                      <Wrench size={10} />
                      {tc.name}
                    </span>
                  ))}
                </div>
              )}

              <div className="text-xs text-gray-600 mt-1">
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
              <div className="flex items-center gap-1.5 text-gray-400 text-xs">
                <RefreshCw size={12} className="animate-spin" />
                Agent analizuje rynek...
                <span className="text-gray-600 ml-1">{loadingTime}s</span>
              </div>
              {loadingTime > 15 && (
                <div className="flex items-center gap-1 text-xs text-amber-500/70 mt-1">
                  <AlertTriangle size={10} />
                  {loadingTime > 60 ? 'Złożona analiza z narzędziami...' : 'Pobieranie danych rynkowych...'}
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
          placeholder={!agentAvailable ? 'Agent offline — sprawdź API' : 'Zapytaj agenta... (Enter = wyślij)'}
          disabled={loading || !agentAvailable}
          rows={2}
          className="flex-1 bg-dark-secondary border border-dark-secondary focus:border-accent-green/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none transition-colors outline-none disabled:opacity-40"
        />
        <button
          onClick={() => void sendMessage(input)}
          disabled={loading || !input.trim() || !agentAvailable}
          className="self-end px-3 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white rounded-lg transition-colors"
        >
          <Send size={16} />
        </button>
      </div>

      {/* Memory info */}
      {threadId && (
        <div className="text-xs text-gray-600 mt-1 text-center">
          🧠 Wątek: {threadId.slice(-8)} — agent pamięta tę rozmowę
        </div>
      )}
    </div>
  );
}

