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
python manage.py migrate --noinput
python manage.py preparar_desarrollo
pkill -f "uvicorn config.asgi:application" 2>/dev/null || true
nohup uvicorn config.asgi:application --host 127.0.0.1 --port 8000 > .scratch/backend_dev.log 2>&1 &
# Trabajador de la fila central (evalúa en segundo plano). Al detenerse con
# SIGTERM devuelve a la fila lo que tenía a medias.
pkill -TERM -f "manage.py trabajar_fila" 2>/dev/null || true
sleep 2
nohup python manage.py trabajar_fila --capacidad "${MAX_WORKERS:-2}" > .scratch/fila_dev.log 2>&1 &

cd "$BACKEND/../frontend"
if ! curl -s -o /dev/null http://localhost:5173/; then
  nohup npm run dev -- --host 127.0.0.1 --port 5173 > "$BACKEND/.scratch/frontend_dev.log" 2>&1 &
fi
echo "PostgreSQL :5433 · Fila: .scratch/fila_dev.log · API http://localhost:8000/api/docs · App http://localhost:5173"
