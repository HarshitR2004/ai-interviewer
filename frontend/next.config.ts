import type { NextConfig } from "next";
const config: NextConfig = {
  // Preparation can include several sequential requests; keep the lobby connected.
  experimental: { proxyTimeout: 600_000, proxyClientMaxBodySize: "12mb" },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};
export default config;
