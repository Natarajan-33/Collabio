import { fileURLToPath } from "node:url"

import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // Pin the Turbopack root to this app. A stray lockfile higher up the tree
  // would otherwise make Next infer the wrong workspace root.
  turbopack: {
    root: fileURLToPath(new URL(".", import.meta.url)),
  },
}

export default nextConfig
