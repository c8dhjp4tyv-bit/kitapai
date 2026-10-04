/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API kökü, örn. https://makine.tailnet.ts.net */
  readonly VITE_API_URL?: string;
  /** Sunucuda KITAPAI_API_KEY ayarlıysa gereklidir. */
  readonly VITE_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
