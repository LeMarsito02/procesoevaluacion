#!/bin/bash
# Medición final: levanta el backend (solo caché de Drive) y evalúa cada
# proponente una vez con la pasada única, comparando con el Segundo Informe.
cd "$(dirname "$0")"
source venv/bin/activate
pkill -9 -f "uvicorn app.main:app" 2>/dev/null
sleep 2
DRIVE_SOLO_CACHE=1 MAX_WORKERS=${MAX_WORKERS:-2} nohup uvicorn app.main:app --port 8000 > .scratch/backend_medicion.log 2>&1 &
for i in $(seq 1 60); do curl -s http://localhost:8000/api/health > /dev/null && break; sleep 2; done
inicio=$(date +%s)
DRIVE_SOLO_CACHE=1 python3 -u scratch_medicion.py
echo "TIEMPO TOTAL (reloj): $(( ($(date +%s) - inicio) / 60 )) min"
pkill -9 -f "uvicorn app.main:app" 2>/dev/null
echo "MEDICION TERMINADA"
