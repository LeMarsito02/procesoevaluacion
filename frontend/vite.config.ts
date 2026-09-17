import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo el frontend y la API comparten origen a través del proxy
// (igual que en producción detrás del proxy inverso): la cookie de sesión es
// de primera parte y no hace falta CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
