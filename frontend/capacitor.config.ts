import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "co.apuestasintel.app",
  appName: "Apuestas Intel CO",
  webDir: "out",
  backgroundColor: "#0d0d0d",
  android: { allowMixedContent: false, adjustMarginsForEdgeToEdge: "force" },
  server: { androidScheme: "https" },
};

export default config;
