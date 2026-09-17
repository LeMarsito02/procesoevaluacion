import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import Raiz from './Raiz.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Raiz />
  </StrictMode>,
)
