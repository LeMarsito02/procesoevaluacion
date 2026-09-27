import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { ProveedorDialogos } from './dialogos.tsx'
import Raiz from './Raiz.tsx'

const raiz = createRoot(document.getElementById('root')!)

// Banco de pruebas visual de los componentes de revisión (#/previsualizacion):
// permite mirarlos con datos inventados, sin crear un proceso ni iniciar
// sesión, y ver cómo se comportan en pantalla angosta. La condición es
// estática, así que en el paquete de producción esta rama y el archivo entero
// desaparecen.
if (import.meta.env.DEV && window.location.hash.startsWith('#/previsualizacion')) {
  void import('./paginas/Previsualizacion.tsx').then(({ default: Previsualizacion }) =>
    raiz.render(
      <StrictMode>
        <ProveedorDialogos>
          <Previsualizacion />
        </ProveedorDialogos>
      </StrictMode>,
    ),
  )
} else {
  raiz.render(
    <StrictMode>
      <ProveedorDialogos>
        <Raiz />
      </ProveedorDialogos>
    </StrictMode>,
  )
}
