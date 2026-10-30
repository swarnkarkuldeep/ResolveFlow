import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': apiTarget } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
