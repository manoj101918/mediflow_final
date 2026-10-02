import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: { port: 5173, strictPort: true },
  build: {
    // Pages and the booking sheet are split out; the entry chunk is the shared runtime every
    // screen needs (React DOM, router, supabase-js, react-query, zod): ~150 kB gzipped.
    chunkSizeWarningLimit: 550,
  },
})
