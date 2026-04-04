import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App.tsx'
import './index.css'

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

