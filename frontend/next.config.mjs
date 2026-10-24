/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://localhost:8000";
const isStatic = process.env.NEXT_PUBLIC_MODE === "static";
// Para GitHub Pages de proyecto (https://usuario.github.io/Apuestas/) se usa NEXT_PUBLIC_BASE_PATH=/Apuestas
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

// Modo app (APK / web estática): exportación estática, sin servidor.
const nextConfig = isStatic
  ? { output: "export", trailingSlash: true, images: { unoptimized: true }, reactStrictMode: true, basePath, assetPrefix: basePath || undefined }
  : {
      output: "standalone",
      reactStrictMode: true,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
      },
    };

export default nextConfig;
