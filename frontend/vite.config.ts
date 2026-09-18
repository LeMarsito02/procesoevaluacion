import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo el frontend y la API comparten origen a través del proxy
// (igual que en producción detrás del proxy inverso): la cookie de sesión es
// de primera parte y no hace falta CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // API_DESTINO permite apuntar a otro backend (p. ej. mientras una
      // medición ocupa el puerto 8000).
      '/api': process.env.API_DESTINO ?? 'http://localhost:8000',
    },
  },
})
