/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Premium dark theme with better colors
        'dark-bg': '#0f0f1e',
        'dark-surface': '#1a1a2e',
        'dark-secondary': '#26264f',
        'dark-tertiary': '#16213e',

        // Accent colors - modern and vibrant
        'accent-green': '#00ff88',
        'accent-green-dark': '#00cc6a',
        'accent-red': '#ff3355',
        'accent-red-dark': '#cc2844',
        'accent-blue': '#00d4ff',
        'accent-blue-dark': '#0099cc',
        'accent-cyan': '#00f5ff',
        'accent-purple': '#a78bfa',
        'accent-orange': '#ff9d3d',

        // Additional colors
        'neon-pink': '#ff006e',
        'neon-purple': '#8338ec',
        'neon-cyan': '#3a86ff',
      },
      fontFamily: {
        'mono': ['JetBrains Mono', 'IBM Plex Mono', 'monospace'],
        'sans': ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        'display': ['Space Grotesk', 'sans-serif'],
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
      spacing: {
        'gutter': '2rem',
      },
      backdropBlur: {
        'xs': '2px',
        'sm': '4px',
      },
      boxShadow: {
        'glow': '0 0 20px rgba(0, 255, 136, 0.3)',
        'glow-red': '0 0 20px rgba(255, 51, 85, 0.3)',
        'glow-blue': '0 0 20px rgba(0, 212, 255, 0.3)',
        'neon': '0 0 30px rgba(163, 230, 53, 0.5)',
      },
      animation: {
        'pulse-green': 'pulse-green 0.3s ease-in-out',
        'pulse-red': 'pulse-red 0.3s ease-in-out',
        'pulse-blue': 'pulse-blue 0.3s ease-in-out',
        'flash': 'flash 0.5s ease-in-out',
        'glow': 'glow 2s ease-in-out infinite',
        'float': 'float 3s ease-in-out infinite',
      },
      keyframes: {
        'pulse-green': {
          '0%': { backgroundColor: '#00ff88', opacity: '0.5' },
          '100%': { backgroundColor: 'transparent', opacity: '0' },
        },
        'pulse-red': {
          '0%': { backgroundColor: '#ff3355', opacity: '0.5' },
          '100%': { backgroundColor: 'transparent', opacity: '0' },
        },
        'pulse-blue': {
          '0%': { backgroundColor: '#00d4ff', opacity: '0.5' },
          '100%': { backgroundColor: 'transparent', opacity: '0' },
        },
        'flash': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
        'glow': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
        'float': {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
    },
  },
  plugins: [],
}

