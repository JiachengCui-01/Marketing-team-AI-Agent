/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const apiBase =
      process.env.NEXT_PUBLIC_API_BASE ??
      "https://marketing-agent-api-ufgx.onrender.com";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
