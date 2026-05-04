/** @type {import('tailwindcss').Config} */
import animate from 'tailwindcss-animate'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Quant Sentinel design tokens — Revolut + Apple + Outfit, dark-first.
      colors: {
        ink: {
          0: '#000000',
          50: '#0a0a0c',
          100: '#111114',
          200: '#1a1a1f',
          300: '#26262d',
          400: '#3a3a45',
          500: '#5a5a66',
          600: '#8b8b95',
          700: '#bdbdc6',
          800: '#e6e6ea',
          900: '#fafafa',
        },
        gold: {
          400: '#d4af37',
          500: '#caa12a',
          600: '#a8861f',
        },
        bull: '#22c55e',
        bear: '#ef4444',
        neutral: '#a1a1aa',
        info: '#3b82f6',
      },
      fontFamily: {
        sans: ['ui-sans-serif', '-apple-system', 'BlinkMacSystemFont', 'Inter', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['ui-sans-serif', '-apple-system', 'BlinkMacSystemFont', 'Inter', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'JetBrains Mono', 'Menlo', 'monospace'],
      },
      fontSize: {
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
        'mesh-gold': 'radial-gradient(60% 80% at 30% 20%, rgba(212,175,55,0.18) 0%, transparent 60%), radial-gradient(50% 70% at 80% 90%, rgba(212,175,55,0.10) 0%, transparent 60%)',
        'mesh-info': 'radial-gradient(60% 80% at 70% 20%, rgba(59,130,246,0.12) 0%, transparent 60%)',
        'border-fade': 'linear-gradient(180deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%)',
        // Inline SVG fractal noise — replaces grain.png, ~400 bytes, browser-rendered
        'grain': "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.55 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")",
      },
      borderRadius: {
        'xl2': '20px',
        'xl3': '28px',
      },
      boxShadow: {
        'soft': '0 1px 2px rgba(0,0,0,0.05), 0 4px 12px rgba(0,0,0,0.08)',
        'lift': '0 8px 32px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.12)',
        'glow-gold': '0 0 24px rgba(212,175,55,0.15), 0 0 48px rgba(212,175,55,0.05)',
        'glow-bull': '0 0 24px rgba(34,197,94,0.25), 0 0 48px rgba(34,197,94,0.08)',
        'glow-bear': '0 0 24px rgba(239,68,68,0.25), 0 0 48px rgba(239,68,68,0.08)',
        'glow-info': '0 0 24px rgba(59,130,246,0.25), 0 0 48px rgba(59,130,246,0.08)',
      },
      animation: {
        'fade-up':       'fadeUp 0.5s cubic-bezier(0.22, 1, 0.36, 1) both',
        'fade-in':       'fadeIn 0.4s ease-out both',
        'flash-bull':    'flashBull 700ms cubic-bezier(0.22, 1, 0.36, 1)',
        'flash-bear':    'flashBear 700ms cubic-bezier(0.22, 1, 0.36, 1)',
        'shimmer':       'shimmer 1.6s linear infinite',
        'aurora':        'auroraRotate 18s linear infinite',
        'beam-pulse':    'beamPulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-glow':    'pulseGlow 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scroll-reveal': 'scrollReveal linear both',
        // 2026-05-04 night — modernist wow expansion
        'gradient-shift': 'gradientShift 8s ease-in-out infinite',
        'blob':          'blob 16s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float-slow':    'floatSlow 9s ease-in-out infinite',
        'orbit':         'orbit 18s linear infinite',
        'orbit-reverse': 'orbit 24s linear infinite reverse',
        'ripple':        'rippleOut 2.4s cubic-bezier(0, 0, 0.2, 1) infinite',
        'border-rotate': 'borderRotate 6s linear infinite',
        'live-pulse':    'livePulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'marquee':       'marquee 40s linear infinite',
        'marquee-slow':  'marquee 70s linear infinite',
        'breathe':       'breathe 5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'tilt-glow':     'tiltGlow 3s ease-in-out infinite',
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
        flashBull: {
          '0%, 100%': { backgroundColor: 'transparent', boxShadow: 'none' },
          '20%': { backgroundColor: 'rgba(34,197,94,0.18)', boxShadow: '0 0 24px rgba(34,197,94,0.20)' },
        },
        flashBear: {
          '0%, 100%': { backgroundColor: 'transparent', boxShadow: 'none' },
          '20%': { backgroundColor: 'rgba(239,68,68,0.18)', boxShadow: '0 0 24px rgba(239,68,68,0.20)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        auroraRotate: {
          '0%':   { transform: 'translate3d(0,0,0) rotate(0deg)' },
          '100%': { transform: 'translate3d(0,0,0) rotate(360deg)' },
        },
        beamPulse: {
          '0%, 100%': { opacity: '0.45' },
          '50%':      { opacity: '1' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(212,175,55,0.0), 0 0 16px rgba(212,175,55,0.10)' },
          '50%':      { boxShadow: '0 0 0 8px rgba(212,175,55,0.05), 0 0 32px rgba(212,175,55,0.30)' },
        },
        scrollReveal: {
          from: { opacity: '0', transform: 'translateY(24px) scale(0.98)' },
          to:   { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        gradientShift: {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%':      { backgroundPosition: '100% 50%' },
        },
        blob: {
          '0%, 100%': { borderRadius: '60% 40% 30% 70% / 60% 30% 70% 40%' },
          '33%':      { borderRadius: '30% 60% 70% 40% / 50% 60% 30% 60%' },
          '66%':      { borderRadius: '50% 60% 30% 60% / 30% 60% 70% 40%' },
        },
        floatSlow: {
          '0%, 100%': { transform: 'translate3d(0, 0, 0)' },
          '50%':      { transform: 'translate3d(0, -10px, 0)' },
        },
        orbit: {
          from: { transform: 'rotate(0deg) translateX(180px) rotate(0deg)' },
          to:   { transform: 'rotate(360deg) translateX(180px) rotate(-360deg)' },
        },
        rippleOut: {
          '0%':   { transform: 'scale(0.85)', opacity: '0.6' },
          '100%': { transform: 'scale(2.4)',  opacity: '0' },
        },
        borderRotate: {
          from: { '--gb-angle': '0deg' },
          to:   { '--gb-angle': '360deg' },
        },
        livePulse: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(34,197,94,0.45)' },
          '70%':      { boxShadow: '0 0 0 10px rgba(34,197,94,0)' },
        },
        marquee: {
          from: { transform: 'translateX(0)' },
          to:   { transform: 'translateX(-50%)' },
        },
        breathe: {
          '0%, 100%': { transform: 'scale(1)',    opacity: '0.7' },
          '50%':      { transform: 'scale(1.04)', opacity: '1.0' },
        },
        tiltGlow: {
          '0%, 100%': { filter: 'drop-shadow(0 0 8px rgba(212,175,55,0.20))' },
          '50%':      { filter: 'drop-shadow(0 0 24px rgba(212,175,55,0.55))' },
        },
      },
    },
  },
  plugins: [animate],
}
