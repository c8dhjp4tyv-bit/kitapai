import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Ortak API sözleşmesi depo içinden okunur; kopya tutulmaz.
      '@kitapai/shared': fileURLToPath(new URL('../shared/src/index.ts', import.meta.url)),
    },
  },
  server: {
    // Telefondan Tailscale üzerinden açılabilsin diye tüm arayüzlere bağlanır.
    host: true,
    port: 5173,
  },
  build: { outDir: 'dist', sourcemap: true },
});
