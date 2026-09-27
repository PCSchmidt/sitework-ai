import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // GitHub Pages serves the static demo under /<repo>/ (VITE_BASE=/sitework-ai/)
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': 'http://api:8000',
      '/healthz': 'http://api:8000',
      '/live/ws': { target: 'ws://api:8000', ws: true },
    },
  },
})
