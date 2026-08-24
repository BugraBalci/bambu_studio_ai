import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Bind IPv4 loopback only — avoids browsers hitting ::1 while Vite
// listens on 0.0.0.0 / dual-stack, which shows up as ERR_CONNECTION_REFUSED.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Do not fall back to another interface/port if 5173 is taken.
    open: false,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
})
