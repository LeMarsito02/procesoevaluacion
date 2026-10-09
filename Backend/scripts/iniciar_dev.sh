#!/bin/bash
# Arranca el entorno de desarrollo de MiEvaluador: PostgreSQL (clúster de
# usuario, puerto 5433), backend Django (8000), trabajador de la fila y
# frontend Vite (5173). Se puede correr las veces que haga falta: reinicia lo
# que ya estaba corriendo y deja todo arriba.
#
#   Backend/scripts/iniciar_dev.sh
#
# Solo toca los procesos de ESTE proyecto (backend en el 8000, vite en el 5173
# y el trabajador de su fila): en el equipo hay otros proyectos con el mismo
# uvicorn y otro vite, y antes el script los mataba también.
set -e
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PGDATA="$HOME/.local/share/mievaluador/pgdata"
mkdir -p "$BACKEND/.scratch"

detener() {  # $1 = patrón que deben cumplir TODOS los argumentos buscados
  for pid in $(ps -eo pid,args | awk -v pat="$1" '$0 ~ pat && !/awk/ {print $1}'); do
    kill -TERM "$pid" 2>/dev/null || true
  done
}

# Se pregunta si la base RESPONDE, no si «pg_ctl status» la cree viva: tras un
# reinicio queda el postmaster.pid viejo y, si otro proceso heredó ese PID,
# pg_ctl dice «running» sin que nada escuche en el 5433.
if ! pg_isready -q -h 127.0.0.1 -p 5433; then
  if ! pgrep -f -- "postgres.*-D $PGDATA" >/dev/null && [ -f "$PGDATA/postmaster.pid" ]; then
    echo "Archivo de bloqueo viejo de PostgreSQL (reinicio del equipo): se aparta."
    mv "$PGDATA/postmaster.pid" "$PGDATA/postmaster.pid.viejo"
  fi
  pg_ctl -D "$PGDATA" -o "-p 5433 -k /tmp -c listen_addresses=localhost" -l "$HOME/.local/share/mievaluador/postgres.log" start
fi
for _ in $(seq 1 20); do pg_isready -q -h 127.0.0.1 -p 5433 && break; sleep 1; done

cd "$BACKEND"
source venv/bin/activate

# Por defecto solo este equipo. Con EXPONER_EN_RED=1 en .env, también los demás
# equipos de la red local (entorno de desarrollo: sin HTTPS y con DEBUG).
EXPONER=$(grep -E "^EXPONER_EN_RED=" .env 2>/dev/null | tail -1 | cut -d= -f2)
if [ "$EXPONER" = "1" ]; then HOST=0.0.0.0; else HOST=127.0.0.1; fi
python manage.py migrate --noinput
python manage.py preparar_desarrollo   # exige DEBUG: en producción el script se detiene aquí

# En desarrollo el superadministrador ve todas las entidades (en producción
# necesita el permiso temporal de la entidad; settings lo ignora sin DEBUG).
export SUPERADMIN_SIN_PERMISO="${SUPERADMIN_SIN_PERMISO:-1}"

detener "uvicorn config.asgi:application.*--port 8000"
detener "manage.py trabajar_fila"
sleep 2
# Servicio de OCR con PaddleOCR (OCR_MOTOR=paddle en .env). Corre en su propio
# entorno de Python (OCR_ENTORNO, por defecto ~/.local/share/mievaluador-ocr):
# Paddle no tiene paquetes para el Python del backend. Se arranca antes que el
# trabajador y se espera a que cargue el modelo.
MOTOR_OCR=$(grep -E "^OCR_MOTOR=" .env 2>/dev/null | tail -1 | cut -d= -f2)
ENTORNO_OCR=$(grep -E "^OCR_ENTORNO=" .env 2>/dev/null | tail -1 | cut -d= -f2)
ENTORNO_OCR="${ENTORNO_OCR:-$HOME/.local/share/mievaluador-ocr}"
detener "ocr_servicio/servidor.py"
# Se espera a que el anterior suelte el puerto: si no, el nuevo choca con él y no arranca.
for _ in $(seq 1 20); do curl -sf -m 1 http://127.0.0.1:8866/salud >/dev/null || break; sleep 0.5; done
if [ "$MOTOR_OCR" = "paddle" ] && [ -x "$ENTORNO_OCR/bin/python" ]; then
  # GPU compartida con la IA (portátil de 4 GB): se turnan la GPU (ver motor/gpu_turno.py).
  GPU_COMPARTIDA=$(grep -E "^GPU_COMPARTIDA=" .env 2>/dev/null | tail -1 | cut -d= -f2)
  LLM_URL_OCR=$(grep -E "^LLM_URL=" .env 2>/dev/null | tail -1 | cut -d= -f2)
  GPU_COMPARTIDA="${GPU_COMPARTIDA:-0}" LLM_URL="${LLM_URL_OCR:-http://127.0.0.1:11434}" GPU_CANDADO="$BACKEND/cache/gpu.lock" \
    nohup "$ENTORNO_OCR/bin/python" -I "$BACKEND/ocr_servicio/servidor.py" > .scratch/ocr_dev.log 2>&1 &
  for _ in $(seq 1 90); do curl -sf http://127.0.0.1:8866/salud >/dev/null && break; sleep 1; done
fi
nohup uvicorn config.asgi:application --host "$HOST" --port 8000 > .scratch/backend_dev.log 2>&1 &
# Trabajador de la fila central (evalúa en segundo plano). Al detenerse con
# SIGTERM devuelve a la fila lo que tenía a medias.
nohup python manage.py trabajar_fila --capacidad "${MAX_WORKERS:-2}" >> .scratch/fila_dev.log 2>&1 &

cd "$BACKEND/../frontend"
detener "vite.*--port 5173"
sleep 1
nohup npm run dev -- --host "$HOST" --port 5173 > "$BACKEND/.scratch/frontend_dev.log" 2>&1 &

# Esperar a que todo responda y decir cómo quedó.
ok() { printf '  %-14s %s\n' "$1" "$2"; }
for _ in $(seq 1 30); do curl -sf http://127.0.0.1:8000/api/health >/dev/null && break; sleep 1; done
for _ in $(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:5173/ && break; sleep 1; done
echo "MiEvaluador:"
pg_isready -q -h 127.0.0.1 -p 5433 && ok "Base de datos" "arriba (5433)" || ok "Base de datos" "NO RESPONDE"
curl -sf http://127.0.0.1:8000/api/health >/dev/null && ok "Backend" "arriba (8000)" || ok "Backend" "NO RESPONDE · mira Backend/.scratch/backend_dev.log"
pgrep -f "manage.py trabajar_fila" >/dev/null && ok "Trabajador" "arriba" || ok "Trabajador" "NO ARRANCÓ · mira Backend/.scratch/fila_dev.log"
if [ "$MOTOR_OCR" = "paddle" ]; then
  curl -sf http://127.0.0.1:8866/salud >/dev/null && ok "OCR" "PaddleOCR arriba (8866)" || ok "OCR" "NO RESPONDE · se lee con Tesseract · mira Backend/.scratch/ocr_dev.log"
fi
curl -sf -o /dev/null http://127.0.0.1:5173/ && ok "Frontend" "arriba → http://localhost:5173" || ok "Frontend" "NO RESPONDE · mira Backend/.scratch/frontend_dev.log"
if [ "$HOST" = "0.0.0.0" ]; then
  # Las de la red real, no las de Docker ni las de las máquinas virtuales.
  IP=$(ip -4 -o addr show scope global | awk '$2 !~ /^(docker|br-|virbr|veth|tun|wg)/ {print $4}' | cut -d/ -f1 | paste -sd' ' | sed 's/ /:5173 · http:\/\//g')
  ok "En la red" "http://$IP:5173"
fi
