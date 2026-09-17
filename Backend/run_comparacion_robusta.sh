#!/bin/bash
# Corre la comparación requisito por requisito, reiniciando el backend antes
# de cada uno para evitar que la memoria se acumule en una corrida larga.
set -e
cd "$(dirname "$0")"
source venv/bin/activate

for req in ${REQUISITOS:-1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18}; do
  echo "=========================================="
  echo "REQUISITO $req"
  echo "=========================================="

  pkill -9 -f "uvicorn app.main:app" 2>/dev/null || true
  sleep 2

  avail=$(free -m | awk '/Mem:/{print $7}')
  echo "Memoria disponible antes de arrancar: ${avail}MB"
  while [ "$avail" -lt 2000 ]; do
    echo "Memoria baja (${avail}MB), esperando 20s..."
    sleep 20
    avail=$(free -m | awk '/Mem:/{print $7}')
  done

  DRIVE_SOLO_CACHE=1 MAX_WORKERS=${MAX_WORKERS:-2} nohup uvicorn app.main:app --port 8000 > .scratch/backend.log 2>&1 &
  BACKEND_PID=$!
  disown

  for i in 1 2 3 4 5; do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  DRIVE_SOLO_CACHE=1 python3 -u scratch_comparar.py "$req" 2>&1

  kill -9 $BACKEND_PID 2>/dev/null || true
  pkill -9 -f "uvicorn app.main:app" 2>/dev/null || true
  sleep 3
done

echo "=========================================="
echo "TODOS LOS REQUISITOS PENDIENTES COMPLETADOS"
echo "=========================================="
python3 -c "
import json
with open('.scratch/nuestros_resultados.json') as f:
    d = json.load(f)
requisitos = sorted({int(k) for v in d.values() for k in v.keys()})
print('requisitos guardados:', requisitos)
"
