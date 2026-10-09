#!/bin/bash
# Copia de seguridad de MiEvaluador: base de datos completa + archivos subidos
# (plantillas). Pensado para correr a diario (cron o timer de systemd).
#
# Usa el superusuario de mantenimiento (DB_ADMIN_USUARIO): con el usuario de la
# app, la Row-Level Security filtraría las filas y el respaldo quedaría vacío.
#
# Cifrado y fuera del servidor (RF-21 y ANS):
#   RESPALDO_DESTINATARIO_AGE  clave pública de age (age1…): los respaldos quedan
#                              cifrados y en este servidor no hay con qué abrirlos;
#                              la clave privada la guarda la entidad fuera de aquí.
#   RESPALDO_REMOTO            destino de rclone (p. ej. «respaldos:mievaluador»):
#                              copia cada respaldo fuera del servidor principal.
#   CIFRADO_OBLIGATORIO=1      sin destinatario de age, el respaldo falla en vez de
#                              quedar en claro.
#
# Restaurar:
#   age -d -i clave.txt db_FECHA.dump.age > db_FECHA.dump   (si está cifrado)
#   pg_restore -h HOST -p PUERTO -U SUPERUSUARIO -d mievaluador --clean --if-exists db_FECHA.dump
#   tar xzf almacenamiento_FECHA.tar.gz -C Backend/
set -euo pipefail

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
# Una variable que no está en .env da vacío (sin «|| true», set -e cortaba el
# script en silencio y el respaldo nunca se hacía).
# En el contenedor no hay .env: las variables llegan por el entorno, y mandan.
leer() {
  if [ -n "${!1:-}" ]; then echo "${!1}"; return; fi
  [ -f "$BACKEND/.env" ] || return 0
  { grep -E "^$1=" "$BACKEND/.env" || true; } | tail -1 | cut -d= -f2-
}

DB_NOMBRE="$(leer DB_NOMBRE)"
DB_HOST="$(leer DB_HOST)"
DB_PUERTO="$(leer DB_PUERTO)"
DB_ADMIN_USUARIO="$(leer DB_ADMIN_USUARIO)"
DB_ADMIN_CLAVE="$(leer DB_ADMIN_CLAVE)"
DESTINO="${RESPALDO_DIR:-$(leer RESPALDO_DIR)}"
DESTINO="${DESTINO:-$HOME/respaldos/mievaluador}"
DIAS="${RESPALDO_DIAS:-14}"
FECHA="$(date +%Y%m%d_%H%M%S)"
DESTINATARIO="$(leer RESPALDO_DESTINATARIO_AGE)"
REMOTO="$(leer RESPALDO_REMOTO)"
if [ -z "$DESTINATARIO" ] && [ "$(leer CIFRADO_OBLIGATORIO)" = "1" ]; then
  echo "Falta RESPALDO_DESTINATARIO_AGE: con CIFRADO_OBLIGATORIO=1 no se deja un respaldo en claro." >&2
  exit 1
fi

mkdir -p "$DESTINO"
chmod 700 "$DESTINO"

PGPASSWORD="$DB_ADMIN_CLAVE" pg_dump -h "$DB_HOST" -p "$DB_PUERTO" -U "$DB_ADMIN_USUARIO" -Fc "$DB_NOMBRE" > "$DESTINO/db_$FECHA.dump"
# Verifica que el archivo se pueda leer antes de darlo por bueno.
pg_restore --list "$DESTINO/db_$FECHA.dump" > /dev/null

if [ -d "$BACKEND/almacenamiento" ]; then
  tar czf "$DESTINO/almacenamiento_$FECHA.tar.gz" -C "$BACKEND" almacenamiento
fi

# Cifrado con la clave pública: el archivo en claro se borra en cuanto el
# cifrado existe y se comprobó que no está vacío.
if [ -n "$DESTINATARIO" ]; then
  for f in "$DESTINO"/db_"$FECHA".dump "$DESTINO"/almacenamiento_"$FECHA".tar.gz; do
    [ -f "$f" ] || continue
    age -r "$DESTINATARIO" -o "$f.age" "$f"
    [ -s "$f.age" ] || { echo "El cifrado de $(basename "$f") quedó vacío." >&2; exit 1; }
    rm -f "$f"
  done
fi

( cd "$DESTINO" && sha256sum ./*_"$FECHA".* > "sumas_$FECHA.sha256" )
chmod 600 "$DESTINO"/*_"$FECHA".*

if [ -n "$REMOTO" ]; then
  rclone copy "$DESTINO" "$REMOTO" --include "*_$FECHA.*"
  # Comprueba que llegó lo mismo que salió.
  rclone check "$DESTINO" "$REMOTO" --include "*_$FECHA.*" --one-way
fi

# Rotación: se conservan los últimos $DIAS días.
find "$DESTINO" -maxdepth 1 -type f \( -name 'db_*.dump' -o -name 'db_*.dump.age' -o -name 'almacenamiento_*.tar.gz' -o -name 'almacenamiento_*.tar.gz.age' -o -name 'sumas_*.sha256' \) -mtime +"$DIAS" -delete

DB_ARCHIVO="$(ls "$DESTINO"/db_"$FECHA".dump* | head -1)"
echo "Respaldo listo en $DESTINO ($(du -sh "$DB_ARCHIVO" | cut -f1) de base de datos$([ -n "$DESTINATARIO" ] && echo ', cifrado')$([ -n "$REMOTO" ] && echo ", copiado a $REMOTO"))"
