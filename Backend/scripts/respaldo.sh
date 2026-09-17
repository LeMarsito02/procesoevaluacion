#!/bin/bash
# Copia de seguridad de MiEvaluador: base de datos completa + archivos subidos
# (plantillas). Pensado para correr a diario (cron o timer de systemd).
#
# Usa el superusuario de mantenimiento (DB_ADMIN_USUARIO): con el usuario de la
# app, la Row-Level Security filtraría las filas y el respaldo quedaría vacío.
#
# Restaurar:
#   pg_restore -h HOST -p PUERTO -U SUPERUSUARIO -d mievaluador --clean --if-exists db_FECHA.dump
#   tar xzf almacenamiento_FECHA.tar.gz -C Backend/
set -euo pipefail

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
leer() { grep -E "^$1=" "$BACKEND/.env" | tail -1 | cut -d= -f2-; }

DB_NOMBRE="$(leer DB_NOMBRE)"
DB_HOST="$(leer DB_HOST)"
DB_PUERTO="$(leer DB_PUERTO)"
DB_ADMIN_USUARIO="$(leer DB_ADMIN_USUARIO)"
DB_ADMIN_CLAVE="$(leer DB_ADMIN_CLAVE)"
DESTINO="${RESPALDO_DIR:-$(leer RESPALDO_DIR)}"
DESTINO="${DESTINO:-$HOME/respaldos/mievaluador}"
DIAS="${RESPALDO_DIAS:-14}"
FECHA="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

PGPASSWORD="$DB_ADMIN_CLAVE" pg_dump -h "$DB_HOST" -p "$DB_PUERTO" -U "$DB_ADMIN_USUARIO" -Fc "$DB_NOMBRE" > "$DESTINO/db_$FECHA.dump"
# Verifica que el archivo se pueda leer antes de darlo por bueno.
pg_restore --list "$DESTINO/db_$FECHA.dump" > /dev/null

if [ -d "$BACKEND/almacenamiento" ]; then
  tar czf "$DESTINO/almacenamiento_$FECHA.tar.gz" -C "$BACKEND" almacenamiento
fi

( cd "$DESTINO" && sha256sum ./*_"$FECHA".* > "sumas_$FECHA.sha256" )
chmod 600 "$DESTINO"/*_"$FECHA".*

# Rotación: se conservan los últimos $DIAS días.
find "$DESTINO" -maxdepth 1 -type f \( -name 'db_*.dump' -o -name 'almacenamiento_*.tar.gz' -o -name 'sumas_*.sha256' \) -mtime +"$DIAS" -delete

echo "Respaldo listo en $DESTINO ($(du -sh "$DESTINO/db_$FECHA.dump" | cut -f1) de base de datos)"
