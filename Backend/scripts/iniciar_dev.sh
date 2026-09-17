#!/bin/bash
# Arranca el entorno de desarrollo de MiEvaluador: PostgreSQL (clúster de
# usuario, puerto 5433), backend Django (8000) y frontend Vite (5173).
set -e
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PGDATA="$HOME/.local/share/mievaluador/pgdata"

if ! pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
  pg_ctl -D "$PGDATA" -o "-p 5433 -k /tmp -c listen_addresses=localhost" -l "$HOME/.local/share/mievaluador/postgres.log" start
fi

cd "$BACKEND"
source venv/bin/activate

# Por defecto solo este equipo. Con EXPONER_EN_RED=1 en .env, también los demás
# equipos de la red local (entorno de desarrollo: sin HTTPS y con DEBUG).
EXPONER=$(grep -E "^EXPONER_EN_RED=" .env 2>/dev/null | tail -1 | cut -d= -f2)
if [ "$EXPONER" = "1" ]; then HOST=0.0.0.0; else HOST=127.0.0.1; fi
python manage.py migrate --noinput
python manage.py preparar_desarrollo
pkill -f "uvicorn config.asgi:application" 2>/dev/null || true
nohup uvicorn config.asgi:application --host "$HOST" --port 8000 > .scratch/backend_dev.log 2>&1 &
# Trabajador de la fila central (evalúa en segundo plano). Al detenerse con
# SIGTERM devuelve a la fila lo que tenía a medias.
pkill -TERM -f "manage.py trabajar_fila" 2>/dev/null || true
sleep 2
nohup python manage.py trabajar_fila --capacidad "${MAX_WORKERS:-2}" > .scratch/fila_dev.log 2>&1 &

cd "$BACKEND/../frontend"
# Se reinicia siempre: si ya estaba corriendo podría estar escuchando en otra dirección.
for pid in $(ps -eo pid,cmd | awk '/node .*vite/ && !/awk/ {print $1}'); do kill "$pid" 2>/dev/null; done
sleep 1
nohup npm run dev -- --host "$HOST" --port 5173 > "$BACKEND/.scratch/frontend_dev.log" 2>&1 &
if [ "$HOST" = "0.0.0.0" ]; then
  IP=$(ip -4 addr show scope global | awk '/inet /{print $2}' | cut -d/ -f1 | head -1)
  echo "PostgreSQL :5433 · Fila: .scratch/fila_dev.log · App http://localhost:5173 · En la red: http://$IP:5173"
else
  echo "PostgreSQL :5433 · Fila: .scratch/fila_dev.log · API http://localhost:8000/api/docs · App http://localhost:5173"
fi
