import { defineConfig, devices } from '@playwright/test'

// End-to-end tests run the real app against the compose backend (`make up`).
const PORT = 5174

export default defineConfig({
  testDir: './e2e',
  timeout: 240_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${String(PORT)}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx vite --port ${String(PORT)} --strictPort`,
    port: PORT,
    reuseExistingServer: true,
  },
})
