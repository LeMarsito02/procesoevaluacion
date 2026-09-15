from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import workers
from app.routers import procesos


@asynccontextmanager
async def lifespan(app: FastAPI):
    workers.iniciar_pool()
    yield
    workers.detener_pool()


app = FastAPI(title="Proceso de Evaluación - API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(procesos.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
