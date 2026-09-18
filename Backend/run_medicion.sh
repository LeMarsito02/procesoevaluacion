#!/bin/bash
# Medición final: levanta el backend (solo caché de Drive) y evalúa cada
# proponente una vez con la pasada única, comparando con el Segundo Informe.
cd "$(dirname "$0")"
source venv/bin/activate
# La base de datos debe estar arriba: la medición entra por la API como un usuario.
PGDATA="$HOME/.local/share/mievaluador/pgdata"
if ! pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
  pg_ctl -D "$PGDATA" -o "-p 5433 -k /tmp -c listen_addresses=localhost" -l "$HOME/.local/share/mievaluador/postgres.log" start
fi
pkill -9 -f "uvicorn config.asgi:application" 2>/dev/null
# El trabajador de la fila compite por CPU y RAM: se detiene durante la medición.
pkill -TERM -f "manage.py trabajar_fila" 2>/dev/null
sleep 2
DRIVE_SOLO_CACHE=${DRIVE_SOLO_CACHE:-1} MAX_WORKERS=${MAX_WORKERS:-2} nohup uvicorn config.asgi:application --port 8000 > .scratch/backend_medicion.log 2>&1 &
for i in $(seq 1 60); do curl -s http://localhost:8000/api/health > /dev/null && break; sleep 2; done
inicio=$(date +%s)
DRIVE_SOLO_CACHE=${DRIVE_SOLO_CACHE:-1} python3 -u scratch_medicion.py
echo "TIEMPO TOTAL (reloj): $(( ($(date +%s) - inicio) / 60 )) min"
pkill -9 -f "uvicorn config.asgi:application" 2>/dev/null
pkill -9 -f "multiprocessing.spawn|multiprocessing.forkserver" 2>/dev/null
echo "MEDICION TERMINADA"
