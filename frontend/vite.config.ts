import { defineConfig, type PluginOption } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import viteCompression from 'vite-plugin-compression'
// PWA disabled: vite-plugin-pwa 0.19.8 not Vite 8 compatible.
// import { VitePWA } from 'vite-plugin-pwa'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig(({ mode }) => ({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },

  plugins: [
    react(),
    tailwindcss(),

    // ── Brotli pre-compression (~15-20% smaller than gzip) ──
    viteCompression({
      algorithm: 'brotliCompress',
      ext: '.br',
      threshold: 1024,
      deleteOriginFile: false,
    }) as PluginOption,

    // ── Gzip fallback for older clients ──
    viteCompression({
      algorithm: 'gzip',
      ext: '.gz',
      threshold: 1024,
      deleteOriginFile: false,
    }) as PluginOption,

    // ── Bundle analyzer (run: npm run analyze) ──
    ...(process.env.ANALYZE ? [visualizer({
      open: true,
      filename: 'dist/bundle-analysis.html',
      gzipSize: true,
      brotliSize: true,
    }) as PluginOption] : []),

    // ── PWA DISABLED ──
    // vite-plugin-pwa 0.19.8 doesn't support Vite 8 — silently fails to
    // emit manifest.webmanifest + registerSW.js while still injecting
    // <link>/<script> refs in index.html → 404s + JS syntax errors on load.
    // No v1.x of vite-plugin-pwa supports Vite 8 yet. Re-enable when
    // ecosystem catches up (restore from git history commit 403c922).
  ],

  server: {
    port: 5173,
    host: '0.0.0.0',
    strictPort: false,

    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '/api'),
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    }
  },

  build: {
    outDir: 'dist',
    sourcemap: mode !== 'production',
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: mode === 'production',
        drop_debugger: true,
        passes: 2,
      }
    },

    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('react') || id.includes('react-dom') ||
                id.includes('react-router') || id.includes('@tanstack/react-query') ||
                id.includes('axios') || id.includes('zustand')) {
              return 'vendor';
            }
            if (id.includes('lightweight-charts')) {
              return 'charts';
            }
          }
        },
        // lucide-react: let Vite tree-shake per-page (only ~15 icons used)
        chunkFileNames: 'chunks/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]'
      }
    },

    cssCodeSplit: true,
    reportCompressedSize: true,
    chunkSizeWarningLimit: 600,
    target: 'es2020',
  },

  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      '@tanstack/react-query',
      'axios',
      'zustand',
      'lightweight-charts',
      'lucide-react',
      'idb-keyval',
    ],
  },
}))
