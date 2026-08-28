/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return {
      fallback: [
        {
          source: "/api/:path*",
          destination: "/api/index.py",
        },
      ],
    };
  },
};
module.exports = nextConfig;
