import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App.tsx'
import { initPerformanceMonitoring } from './hooks/usePerformanceMonitor'
import './i18n'  // initializes react-i18next — auto-detects browser language (pl/en)
import './index.css'

// Initialize Web Vitals monitoring (dev only — logs FCP, LCP, CLS, TTFB)
initPerformanceMonitoring();

// Suppress Chrome extension noise (not app bugs — from adblock/PW managers/etc)
const EXT_ERROR_PATTERNS = [
  'No Listener',
  'tabs:outgoing',
  'message channel closed',        // chrome.runtime async listener mismatch
  'Extension context invalidated', // extension reloaded mid-session
  'asynchronous response',         // same as message channel closed, other wording
];

function isExtensionError(msg: string | undefined): boolean {
  if (!msg) {return false;}
  return EXT_ERROR_PATTERNS.some(p => msg.includes(p));
}

window.addEventListener('error', (e) => {
  if (isExtensionError(e.message)) {e.preventDefault();}
});
window.addEventListener('unhandledrejection', (e) => {
  const msg = e.reason?.message ?? String(e.reason);
  if (isExtensionError(msg)) {e.preventDefault();}
});

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Failed to find root element')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

