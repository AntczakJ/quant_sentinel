/**
 * AgentChat.tsx — Quant Sentinel Gold Trader Agent chat interface.
 */

import { useState, useRef, useEffect, useCallback, memo } from 'react';
import { Send, Bot, User, Wrench, RefreshCw, Trash2, AlertTriangle, History, Plus, ChevronLeft, Mic, MicOff, Copy, Check } from 'lucide-react';
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
const THREADS_LIST_KEY = 'qs_agent_threads';

interface ThreadInfo {
  id: string;
  label: string;
  lastUsed: number;
}

function loadThreads(): ThreadInfo[] {
  try {
    return JSON.parse(localStorage.getItem(THREADS_LIST_KEY) ?? '[]');
  } catch { return []; }
}

function saveThreads(threads: ThreadInfo[]) {
  localStorage.setItem(THREADS_LIST_KEY, JSON.stringify(threads.slice(0, 20)));
}

const QUICK_ACTIONS = [
  { label: 'Analiza M15', message: 'Przeanalizuj XAU/USD na M15 i ocen aktualny setup SMC.' },
  { label: 'Sygnal', message: 'Wygeneruj sygnal tradingowy na M15 z kapitalem 10000 USD.' },
  { label: 'Newsy', message: 'Pobierz najnowsze newsy i zinterpretuj ich wplyw na zloto.' },
  { label: 'Kalendarz', message: 'Sprawdz nadchodzace wydarzenia makro USD (NFP, CPI, FOMC).' },
  { label: 'Portfolio', message: 'Pokaz statystyki portfela i ostatnie wyniki.' },
];

/** Copy button for agent responses */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);
  return (
    <button onClick={handleCopy} className="p-0.5 rounded text-th-dim hover:text-th-muted transition-colors" title="Kopiuj">
      {copied ? <Check size={10} className="text-accent-green" /> : <Copy size={10} />}
    </button>
  );
}

export const AgentChat = memo(function AgentChat() {
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
  const [showHistory, setShowHistory] = useState(false);
  const [threads, setThreads] = useState<ThreadInfo[]>(loadThreads);
  const apiConnected = useTradingStore((s) => s.apiConnected);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isAbortedRef = useRef(false);

  // Voice input (Web Speech API)
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  const speechSupported = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

  const toggleVoice = useCallback(() => {
    if (listening && recognitionRef.current) {
      recognitionRef.current.stop();
      setListening(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.lang = 'pl-PL';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInput(prev => prev ? prev + ' ' + transcript : transcript);
      setListening(false);
    };

    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [listening]);

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
        // Track thread in history
        setThreads(prev => {
          const existing = prev.filter(t => t.id !== result.thread_id);
          const label = text.trim().slice(0, 40) + (text.trim().length > 40 ? '...' : '');
          const updated = [{ id: result.thread_id, label, lastUsed: Date.now() }, ...existing];
          saveThreads(updated);
          return updated;
        });
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

  const loadThread = useCallback(async (tid: string) => {
    try {
      setLoading(true);
      const history = await agentAPI.getThreadHistory(tid, 50);
      const msgs: Message[] = history.messages.map((m: { role: string; content: string; created_at: number }) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        timestamp: new Date(m.created_at * 1000),
      }));
      setMessages(msgs.length > 0 ? msgs : [{
        role: 'assistant' as const,
        content: 'Watek zaladowany — brak wiadomosci do wyswietlenia.',
        timestamp: new Date(),
      }]);
      setThreadId(tid);
      localStorage.setItem(THREAD_STORAGE_KEY, tid);
      setShowHistory(false);
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant' as const,
        content: 'Nie udalo sie zaladowac watku.',
        timestamp: new Date(),
      }]);
    } finally {
      setLoading(false);
    }
  }, []);

  const startNewThread = useCallback(() => {
    localStorage.removeItem(THREAD_STORAGE_KEY);
    setThreadId(undefined);
    setMessages([{
      role: 'assistant' as const,
      content: 'Nowy watek — zaczynam od nowa!',
      timestamp: new Date(),
    }]);
    setShowHistory(false);
  }, []);

  const resetThread = () => {
    if (messages.length > 1 && !window.confirm('Wyczyścić historię rozmowy?')) return;
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
        <div className="flex items-center gap-1.5">
          {threads.length > 0 && (
            <button
              onClick={() => setShowHistory(v => !v)}
              title="Historia watkow"
              className={`p-1 rounded transition-colors ${showHistory ? 'text-accent-blue bg-accent-blue/10' : 'text-th-muted hover:text-th-secondary'}`}
            >
              <History size={14} />
            </button>
          )}
          <button
            onClick={startNewThread}
            title="Nowy watek"
            className="text-th-muted hover:text-accent-green transition-colors"
          >
            <Plus size={14} />
          </button>
          <button
            onClick={resetThread}
            title="Wyczysc historie rozmowy"
            className="text-th-muted hover:text-accent-red transition-colors"
          >
            <Trash2 size={14} />
          </button>
        </div>
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

      {/* Thread history sidebar */}
      {showHistory && (
        <div className="mb-3 bg-dark-bg border border-dark-secondary rounded-lg p-2 max-h-48 overflow-y-auto space-y-1">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-th-muted uppercase tracking-wider font-medium">Poprzednie watki</span>
            <button onClick={() => setShowHistory(false)} className="text-th-dim hover:text-th-muted">
              <ChevronLeft size={12} />
            </button>
          </div>
          {threads.map(t => (
            <button
              key={t.id}
              onClick={() => void loadThread(t.id)}
              className={`w-full text-left px-2 py-1.5 rounded text-xs transition-colors hover:bg-dark-secondary ${
                t.id === threadId ? 'bg-accent-blue/10 text-accent-blue border border-accent-blue/20' : 'text-th-secondary'
              }`}
            >
              <div className="truncate font-medium">{t.label || t.id.slice(-8)}</div>
              <div className="text-[9px] text-th-dim">
                {new Date(t.lastUsed).toLocaleString('pl-PL', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
              </div>
            </button>
          ))}
        </div>
      )}

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

              {/* Copy button for assistant messages */}
              {msg.role === 'assistant' && (
                <div className="flex justify-end mt-1">
                  <CopyButton text={msg.content} />
                </div>
              )}

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
        {speechSupported && (
          <button
            onClick={toggleVoice}
            disabled={loading || !agentAvailable}
            className={`self-end px-2.5 py-2 rounded-lg transition-all disabled:opacity-40 ${
              listening
                ? 'bg-accent-red text-white animate-pulse'
                : 'bg-dark-secondary text-th-muted hover:text-th-secondary'
            }`}
            title={listening ? 'Stop nagrywania' : 'Mow do agenta'}
          >
            {listening ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
        )}
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
});
