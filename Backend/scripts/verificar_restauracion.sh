#!/bin/bash
# Prueba de restauración del último respaldo (ISO/IEC 27001, control 8.13): un
# respaldo que nunca se ha restaurado no está probado.
#
#   Backend/scripts/verificar_restauracion.sh [archivo.dump]
#
# Comprueba las sumas sha256, restaura el respaldo en una base TEMPORAL (no toca
# la de la aplicación), cuenta las filas de las tablas principales, verifica la
# cadena de huellas de la auditoría y borra la base temporal. Deja el resultado
# en restauraciones.log, junto a los respaldos: esa es la evidencia.
set -euo pipefail

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
# Una variable que no está en .env da vacío (sin «|| true», set -e cortaba el
# script en silencio y el respaldo nunca se hacía).
leer() { { grep -E "^$1=" "$BACKEND/.env" || true; } | tail -1 | cut -d= -f2-; }

DB_HOST="$(leer DB_HOST)"
DB_PUERTO="$(leer DB_PUERTO)"
DB_ADMIN_USUARIO="$(leer DB_ADMIN_USUARIO)"
export PGPASSWORD="$(leer DB_ADMIN_CLAVE)"
DESTINO="${RESPALDO_DIR:-$(leer RESPALDO_DIR)}"
DESTINO="${DESTINO:-$HOME/respaldos/mievaluador}"

DUMP="${1:-$(ls -t "$DESTINO"/db_*.dump 2>/dev/null | head -1)}"
[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "No hay respaldos en $DESTINO: corra primero scripts/respaldo.sh"; exit 1; }
FECHA="$(basename "$DUMP" .dump | sed 's/^db_//')"
TEMPORAL="mievaluador_restauracion_$(date +%s)"
psql_() { psql -h "$DB_HOST" -p "$DB_PUERTO" -U "$DB_ADMIN_USUARIO" -v ON_ERROR_STOP=1 "$@"; }

# 1. Integridad: el archivo es el mismo que se guardó.
if [ -f "$DESTINO/sumas_$FECHA.sha256" ]; then
  ( cd "$DESTINO" && sha256sum --check --quiet "sumas_$FECHA.sha256" )
  INTEGRIDAD="sumas sha256 correctas"
else
  INTEGRIDAD="sin archivo de sumas"
fi

# 2. Restauración en una base aparte, que se borra al terminar pase lo que pase.
trap 'psql_ -d postgres -q -c "DROP DATABASE IF EXISTS $TEMPORAL" >/dev/null 2>&1 || true' EXIT
INICIO=$(date +%s)
psql_ -d postgres -q -c "CREATE DATABASE $TEMPORAL"
pg_restore -h "$DB_HOST" -p "$DB_PUERTO" -U "$DB_ADMIN_USUARIO" -d "$TEMPORAL" --no-owner --exit-on-error "$DUMP"
SEGUNDOS=$(( $(date +%s) - INICIO ))

# 3. Lo restaurado tiene datos.
CONTEOS=$(psql_ -d "$TEMPORAL" -At -c "
  SELECT string_agg(t || '=' || n, ' ') FROM (
    SELECT 'entidades' t, count(*) n FROM cuentas_entidad UNION ALL
    SELECT 'usuarios', count(*) FROM cuentas_usuario UNION ALL
    SELECT 'procesos', count(*) FROM evaluaciones_proceso UNION ALL
    SELECT 'resultados', count(*) FROM evaluaciones_resultado UNION ALL
    SELECT 'auditoria', count(*) FROM cuentas_eventoauditoria) x")
USUARIOS=$(psql_ -d "$TEMPORAL" -At -c "SELECT count(*) FROM cuentas_usuario")
[ "$USUARIOS" -gt 0 ] || { echo "La restauración quedó sin usuarios: respaldo inservible"; exit 1; }

# 4. La auditoría restaurada no fue alterada (cadena de huellas).
( cd "$BACKEND" && source venv/bin/activate && DB_NOMBRE="$TEMPORAL" DB_USUARIO="$DB_ADMIN_USUARIO" DB_CLAVE="$PGPASSWORD" \
    python manage.py verificar_auditoria >/dev/null ) && AUDITORIA="cadena de auditoría íntegra" || AUDITORIA="AUDITORÍA CON ERRORES"

LINEA="$(date -Iseconds) · $(basename "$DUMP") · $INTEGRIDAD · restaurado en ${SEGUNDOS}s · $CONTEOS · $AUDITORIA"
echo "$LINEA" | tee -a "$DESTINO/restauraciones.log"
[ "$AUDITORIA" = "cadena de auditoría íntegra" ]
