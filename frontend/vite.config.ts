import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The backend serves its routes at the root; the browser calls them under /api.
const apiTarget = process.env.LODESTAR_API_URL ?? 'http://localhost:8000'
const proxy = {
  '/api': {
    target: apiTarget,
    changeOrigin: true,
    ws: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: '0.0.0.0', port: 5173, proxy },
  preview: { host: '0.0.0.0', port: 5173, proxy },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // Picovoice's packages have only a "module" field, which Node-side resolution ignores.
    alias: [
      {
        find: /^@picovoice\/(porcupine-web|web-voice-processor)$/,
        replacement: '@picovoice/$1/dist/esm/index.js',
      },
    ],
  },
})
