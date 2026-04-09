/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Modern dark theme — deeper, richer tones
        'dark-bg': '#0a0d12',
        'dark-surface': '#0f1318',
        'dark-secondary': '#1a2030',
        'dark-tertiary': '#141920',

        // Accent colors
        'accent-green': '#22c55e',
        'accent-green-dark': '#16a34a',
        'accent-red': '#ef4444',
        'accent-red-dark': '#dc2626',
        'accent-blue': '#3b82f6',
        'accent-blue-dark': '#2563eb',
        'accent-cyan': '#06b6d4',
        'accent-purple': '#8b5cf6',
        'accent-orange': '#f59e0b',
      },
      fontFamily: {
        'mono': ['JetBrains Mono', 'monospace'],
        'sans': ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        'display': ['Inter', 'sans-serif'],
      },
      fontSize: {
        'xs': ['0.75rem', { lineHeight: '1rem' }],
        'sm': ['0.875rem', { lineHeight: '1.25rem' }],
        'base': ['1rem', { lineHeight: '1.5rem' }],
        'lg': ['1.125rem', { lineHeight: '1.75rem' }],
        'xl': ['1.25rem', { lineHeight: '1.75rem' }],
        '2xl': ['1.5rem', { lineHeight: '2rem' }],
        '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
      },
      borderRadius: {
        'xl': '0.875rem',
        '2xl': '1rem',
      },
      boxShadow: {
        'glow': '0 0 8px rgba(34, 197, 94, 0.15)',
        'glow-red': '0 0 8px rgba(239, 68, 68, 0.15)',
        'glow-blue': '0 0 8px rgba(59, 130, 246, 0.15)',
        'panel': '0 4px 24px rgba(0, 0, 0, 0.2)',
      },
    },
  },
  plugins: [],
}
