import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"

import { defineConfig, devices } from "@playwright/test"

// The spec signs in with the seeded demo accounts. Their emails and the shared password
// come from the environment, never from this repo. Anything the shell has not already
// set is read from an optional `.env.e2e` next to this file (git-ignored, like every
// `.env*` here); see README.md.
const envFile = fileURLToPath(new URL(".env.e2e", import.meta.url))
if (existsSync(envFile)) process.loadEnvFile(envFile)

/**
 * End-to-end smoke for M1. It drives the real UI against a running stack: the backend on
 * :8000 (`uv run uvicorn app.main:create_app --factory --port 8000`) and this app on
 * :3000 (`npm run dev`), both pointed at the seeded hosted Supabase project. Start them
 * yourself; nothing here launches a server.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  // The tests share three seeded accounts and one hosted database.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  // Every typed command is routed by real Gemini, and publishing embeds the package.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    // Animations only add waiting: the app snaps to its end state for this preference.
    reducedMotion: "reduce",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
