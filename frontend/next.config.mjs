/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://localhost:8000";
const isStatic = process.env.NEXT_PUBLIC_MODE === "static";
// Para GitHub Pages de proyecto (https://usuario.github.io/Apuestas/) se usa NEXT_PUBLIC_BASE_PATH=/Apuestas
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

// Hora de compilación: la app la compara con la última APK publicada para avisar de actualizaciones.
const env = { NEXT_PUBLIC_BUILD_TIME: new Date().toISOString() };

// Modo app (APK / web estática): exportación estática, sin servidor.
const nextConfig = isStatic
  ? { env, output: "export", trailingSlash: true, images: { unoptimized: true }, reactStrictMode: true, basePath, assetPrefix: basePath || undefined }
  : {
      env,
      output: "standalone",
      reactStrictMode: true,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
      },
    };

export default nextConfig;
