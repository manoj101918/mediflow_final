import { existsSync, readFileSync } from 'node:fs'

import { defineConfig } from '@playwright/test'

// The tests talk to Supabase Auth directly (to fetch tokens for setup/cleanup), so expose the
// frontend's public settings from .env.local to the test process.
if (existsSync('.env.local')) {
  for (const line of readFileSync('.env.local', 'utf8').split(/\r?\n/)) {
    const match = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line)
    if (match && process.env[match[1]!] === undefined) process.env[match[1]!] = match[2]
  }
}

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // Tests share one clinic database; run them one at a time.
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    // Installed Google Chrome by default (no browser download needed). Set
    // E2E_BROWSER_CHANNEL=chromium after `npx playwright install chromium` to use the bundled one.
    channel: process.env.E2E_BROWSER_CHANNEL ?? 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'uv run python -m uvicorn app.main:app --port 8000',
      cwd: '../backend',
      url: 'http://localhost:8000/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
