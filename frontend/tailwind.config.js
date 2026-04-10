/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        /* ═══ Theme-aware surface colors ═══
           These reference CSS variables that switch with dark/light theme.
           Supports Tailwind alpha: bg-dark-bg/50, border-dark-secondary/30 */
        'dark-bg':        'rgb(var(--c-bg) / <alpha-value>)',
        'dark-surface':   'rgb(var(--c-surface) / <alpha-value>)',
        'dark-secondary': 'rgb(var(--c-secondary) / <alpha-value>)',
        'dark-tertiary':  'rgb(var(--c-raised) / <alpha-value>)',

        /* ═══ Theme-aware accent colors ═══ */
        'accent-green':  'rgb(var(--c-green) / <alpha-value>)',
        'accent-red':    'rgb(var(--c-red) / <alpha-value>)',
        'accent-blue':   'rgb(var(--c-blue) / <alpha-value>)',
        'accent-cyan':   'rgb(var(--c-cyan) / <alpha-value>)',
        'accent-purple': 'rgb(var(--c-purple) / <alpha-value>)',
        'accent-orange': 'rgb(var(--c-orange) / <alpha-value>)',

        /* ═══ Theme-aware text colors ═══
           text-th = primary, text-th-secondary, text-th-muted, text-th-dim */
        'th':           'rgb(var(--c-text-1) / <alpha-value>)',
        'th-secondary': 'rgb(var(--c-text-2) / <alpha-value>)',
        'th-muted':     'rgb(var(--c-text-3) / <alpha-value>)',
        'th-dim':       'rgb(var(--c-text-4) / <alpha-value>)',

        /* ═══ Theme-aware border ═══ */
        'th-border':    'rgb(var(--c-border) / <alpha-value>)',
        'th-border-h':  'rgb(var(--c-border-h) / <alpha-value>)',
        'th-hover':     'rgb(var(--c-hover) / <alpha-value>)',
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
        'glow':      '0 0 8px rgb(var(--c-green) / 0.15)',
        'glow-red':  '0 0 8px rgb(var(--c-red) / 0.15)',
        'glow-blue': '0 0 8px rgb(var(--c-blue) / 0.15)',
        'panel':     '0 4px 24px rgba(0, 0, 0, 0.2)',
      },
    },
  },
  plugins: [],
}
