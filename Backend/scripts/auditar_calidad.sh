#!/bin/bash
# Auditoría técnica de calidad y seguridad de MiEvaluador. Deja la evidencia
# fechada en docs/normas/evidencias/AAAA-MM-DD/ (ISO/IEC 25010, ISO/IEC 27001,
# lineamientos de seguridad digital de MinTIC y accesibilidad de la Res. 1519).
#
#   Backend/scripts/auditar_calidad.sh
#
# Corre: pruebas automáticas, vulnerabilidades de dependencias (pip-audit y
# npm audit), análisis estático de seguridad (Bandit), verificación de la
# auditoría, inventario de la IA y accesibilidad WCAG 2.1 AA (axe-core).
# El escaneo de infraestructura y aplicación con Nessus va aparte (ver
# docs/normas/07_GESTION_DE_VULNERABILIDADES.md) y su informe se guarda en la
# misma carpeta.
set -uo pipefail

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$RAIZ/Backend"
FRONTEND="$RAIZ/frontend"
SALIDA="$RAIZ/docs/normas/evidencias/$(date +%F)"
mkdir -p "$SALIDA/accesibilidad"
cd "$BACKEND" && source venv/bin/activate

ORDEN=()
declare -A ESTADO ARCHIVO
paso() {  # $1 = nombre, $2 = archivo de salida, resto = comando
  local nombre="$1" archivo="$2"; shift 2
  echo "▶ $nombre"
  ORDEN+=("$nombre"); ARCHIVO[$nombre]="$archivo"
  if "$@" > "$SALIDA/$archivo" 2>&1; then ESTADO[$nombre]="aprobado"; else ESTADO[$nombre]="CON HALLAZGOS"; fi
}

paso "Pruebas automáticas" pruebas.txt python manage.py test --parallel 4
paso "Dependencias Python (pip-audit)" pip_audit.txt uvx pip-audit -r requirements.txt --progress-spinner off
paso "Dependencias JavaScript (npm audit)" npm_audit.txt npm --prefix "$FRONTEND" audit
paso "Análisis estático (Bandit)" bandit.txt uvx bandit -q -r api cuentas evaluaciones motor config -x '*/tests*,*/migrations/*' -ll
paso "Compilación y lint del frontend" frontend.txt bash -c "cd '$FRONTEND' && npx tsc -b && npx eslint ."
paso "Integridad de la auditoría" auditoria.txt python manage.py verificar_auditoria
paso "Inventario de la IA (ISO 42001)" inventario_ia.txt python manage.py inventario_ia
paso "Accesibilidad WCAG 2.1 AA" accesibilidad.txt python scripts/auditar_accesibilidad.py --internas --salida "$SALIDA/accesibilidad/informe.json"

{
  echo "# Auditoría técnica — $(date '+%F %H:%M')"
  echo
  echo "Versión: $(git -C "$RAIZ" rev-parse --short HEAD) · rama $(git -C "$RAIZ" rev-parse --abbrev-ref HEAD)"
  echo
  echo "| Control | Resultado | Evidencia |"
  echo "|---|---|---|"
  for nombre in "${ORDEN[@]}"; do echo "| $nombre | ${ESTADO[$nombre]} | ${ARCHIVO[$nombre]} |"; done
} > "$SALIDA/RESUMEN.md"
cat "$SALIDA/RESUMEN.md"
echo
echo "Evidencia en $SALIDA"
