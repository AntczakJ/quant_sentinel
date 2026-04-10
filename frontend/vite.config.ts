import { defineConfig, type PluginOption } from 'vite'
import react from '@vitejs/plugin-react'
import viteCompression from 'vite-plugin-compression'
import { VitePWA } from 'vite-plugin-pwa'

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

    // ── PWA + Service Worker for offline caching ──
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      workbox: {
        runtimeCaching: [
          {
            urlPattern: /\.(?:js|css|woff2?)$/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'static-assets',
              expiration: { maxEntries: 80, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
          {
            urlPattern: /\/api\/market\/(candles|ticker|indicators)/,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'market-data',
              expiration: { maxEntries: 30, maxAgeSeconds: 120 },
            },
          },
          {
            urlPattern: /\/api\//,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-responses',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 50, maxAgeSeconds: 300 },
            },
          },
          {
            urlPattern: /\.(?:png|jpg|jpeg|svg|gif|ico|webp)$/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'images',
              expiration: { maxEntries: 30, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
        ],
        globPatterns: ['**/*.{js,css,html,ico,svg,woff2}'],
        globIgnores: ['**/*.map'],
      },
      manifest: {
        name: 'Quant Sentinel — AI Trading',
        short_name: 'Quant Sentinel',
        description: 'Professional AI Trading Platform for XAU/USD',
        theme_color: '#0b0e14',
        background_color: '#0b0e14',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/qs-logo.svg', sizes: '512x512', type: 'image/svg+xml', purpose: 'any maskable' },
        ],
      },
    }),
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

  css: {
    postcss: './postcss.config.js'
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
