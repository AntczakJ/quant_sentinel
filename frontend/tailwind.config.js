/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Quant Sentinel design tokens — synthesized from Revolut (financial
      // gradients), Apple (whitespace + premium), Outfit (bold typography,
      // confident layout choices). Dark-first; light mode flips via .light.
      colors: {
        // Surfaces — true OLED black to layered greys
        ink: {
          0: '#000000',     // canvas
          50: '#0a0a0c',    // page bg
          100: '#111114',   // raised card
          200: '#1a1a1f',   // hover surface
          300: '#26262d',   // border
          400: '#3a3a45',
          500: '#5a5a66',
          600: '#8b8b95',   // muted text
          700: '#bdbdc6',
          800: '#e6e6ea',
          900: '#fafafa',   // primary text on dark
        },
        // Brand accent — premium gold (echoes XAU, also Apple's premium hue)
        gold: {
          400: '#d4af37',
          500: '#caa12a',
          600: '#a8861f',
        },
        // Signal colors — muted/refined, not neon
        bull: '#22c55e',
        bear: '#ef4444',
        neutral: '#a1a1aa',
        info: '#3b82f6',
      },
      fontFamily: {
        // System stack first; Inter as web fallback
        sans: [
          'ui-sans-serif',
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        display: [
          'ui-sans-serif',
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          'Segoe UI',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SF Mono', 'JetBrains Mono', 'Menlo', 'monospace'],
      },
      fontSize: {
        // Apple-inspired typographic scale — generous, breathing
        'display-xl': ['96px', { lineHeight: '0.95', letterSpacing: '-0.04em', fontWeight: '700' }],
        'display-lg': ['72px', { lineHeight: '0.98', letterSpacing: '-0.035em', fontWeight: '700' }],
        'display-md': ['56px', { lineHeight: '1.0', letterSpacing: '-0.03em', fontWeight: '600' }],
        'display-sm': ['40px', { lineHeight: '1.05', letterSpacing: '-0.025em', fontWeight: '600' }],
        'headline':   ['28px', { lineHeight: '1.15', letterSpacing: '-0.015em', fontWeight: '600' }],
        'title':      ['20px', { lineHeight: '1.3', letterSpacing: '-0.01em', fontWeight: '500' }],
        'body':       ['15px', { lineHeight: '1.55', letterSpacing: '-0.005em', fontWeight: '400' }],
        'caption':    ['13px', { lineHeight: '1.4', letterSpacing: '0', fontWeight: '400' }],
        'micro':      ['11px', { lineHeight: '1.3', letterSpacing: '0.04em', fontWeight: '500' }],
      },
      letterSpacing: {
        tightest: '-0.04em',
      },
      backgroundImage: {
        // Subtle financial gradients — Revolut-style, but more restrained
        'mesh-gold': 'radial-gradient(60% 80% at 30% 20%, rgba(212,175,55,0.18) 0%, transparent 60%), radial-gradient(50% 70% at 80% 90%, rgba(212,175,55,0.10) 0%, transparent 60%)',
        'mesh-info': 'radial-gradient(60% 80% at 70% 20%, rgba(59,130,246,0.12) 0%, transparent 60%)',
        'border-fade': 'linear-gradient(180deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%)',
      },
      borderRadius: {
        'xl2': '20px',
        'xl3': '28px',
      },
      boxShadow: {
        // Layered, soft shadows — Apple-inspired
        'soft': '0 1px 2px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.08)',
        'lift': '0 8px 32px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.12)',
        'glow-gold': '0 0 24px rgba(212,175,55,0.15), 0 0 48px rgba(212,175,55,0.05)',
      },
      animation: {
        'fade-up': 'fadeUp 0.5s cubic-bezier(0.22, 1, 0.36, 1) both',
        'fade-in': 'fadeIn 0.4s ease-out both',
      },
      keyframes: {
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
