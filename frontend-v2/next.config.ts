import type { NextConfig } from "next";

// Backend origin used by the server-side rewrite. The browser always calls
// same-origin `/api/*`, so the session cookie and CSRF cookie stay first-party.
const backendUrl = (process.env.BACKEND_URL || "http://localhost:8001").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
