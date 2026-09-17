import { createContext, useContext } from 'react'
import type { Usuario } from './cuentas'

export interface Sesion {
  usuario: Usuario
  salir: () => void
}

export const ContextoSesion = createContext<Sesion | null>(null)

export function useSesion(): Sesion | null {
  return useContext(ContextoSesion)
}

export const puedeGestionarEquipo = (u: Usuario) => u.rol === 'superadmin' || u.rol === 'admin_entidad' || u.rol === 'jefe_area'
