import type { NextConfig } from "next";

// Backend origin used by the server-side rewrite. The browser always calls
// same-origin `/api/*`, so the session cookie and CSRF cookie stay first-party.
const backendUrl = (process.env.BACKEND_URL || "http://localhost:8001").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  output: "standalone",
  // La IA vive agrupada en /ai: se mantienen los enlaces antiguos.
  async redirects() {
    const moved = ["assistant", "advisor", "skills", "automations"];
    return [
      ...moved.flatMap((name) => [
        { source: `/${name}`, destination: `/ai/${name}`, permanent: false },
        { source: `/${name}/:path*`, destination: `/ai/${name}/:path*`, permanent: false },
      ]),
      ...["asistente", "modelos"].map((value) => ({
        source: "/settings",
        has: [{ type: "query" as const, key: "section", value }],
        destination: "/ai/settings",
        permanent: false,
      })),
    ];
  },
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
