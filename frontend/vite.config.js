import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://backend:8000',
      '/health': 'http://backend:8000',
      '/sandbox': 'http://backend:8000',
      '/static/sandbox': 'http://backend:8000',
      '/WebReport/decision/url/power_map': 'http://backend:8000'
    }
  }
})
