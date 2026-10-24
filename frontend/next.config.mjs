/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://localhost:8000";
const isStatic = process.env.NEXT_PUBLIC_MODE === "static";

// Modo app (APK / web estática): exportación estática, sin servidor.
const nextConfig = isStatic
  ? { output: "export", trailingSlash: true, images: { unoptimized: true }, reactStrictMode: true }
  : {
      output: "standalone",
      reactStrictMode: true,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
      },
    };

export default nextConfig;
