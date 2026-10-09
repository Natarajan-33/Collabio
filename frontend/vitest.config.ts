import { fileURLToPath } from "node:url"

import react from "@vitejs/plugin-react"
import { configDefaults, defineConfig } from "vitest/config"

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirror the `@/*` path alias from tsconfig.json.
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    // Playwright owns tests/e2e (`npm run e2e`); Vitest must never try to run it.
    exclude: [...configDefaults.exclude, "tests/e2e/**"],
  },
})
