import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App.tsx'
import { initPerformanceMonitoring } from './hooks/usePerformanceMonitor'
import './i18n'  // initializes react-i18next — auto-detects browser language (pl/en)
import './index.css'

// Initialize Web Vitals monitoring (dev only — logs FCP, LCP, CLS, TTFB)
initPerformanceMonitoring();

// Suppress Chrome extension errors
window.addEventListener('error', (e) => {
  if (e.message?.includes('No Listener') || e.message?.includes('tabs:outgoing')) {
    e.preventDefault();
  }
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

