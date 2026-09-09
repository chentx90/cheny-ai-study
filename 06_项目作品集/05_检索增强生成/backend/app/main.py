from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.retrieve import router as retrieve_router
from .api.system import router as system_router
from .api.methods import router as methods_router
from .api.ingestion import router as ingestion_router
from .api.knowledge import router as knowledge_router
from .api.evaluation import router as evaluation_router
from .core.registry import registry_service
from .adapters.postgres import PostgresAdapter
from .services.ingestion_service import IngestionService
from .config import settings
from contextlib import asynccontextmanager
import asyncpg
import sys


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = None
    try:
        pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=2, max_size=15)
        app.state.db = pool

        adapter = PostgresAdapter(pool=pool)
        registry_service.register(registry_service._backends["postgres_pgvector"], adapter=adapter)

        app.state.ingestion_service = IngestionService(pool)
    except Exception as exc:
        print(f"[WARN] Failed to initialize Postgres: {exc}", file=sys.stderr)
    yield
    if pool:
        await pool.close()


app = FastAPI(title="RAG Modular System", version="0.1.0", lifespan=lifespan)

default_cors_origins = ",".join(
    [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ]
)
cors_origins = settings.cors_origins or default_cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(retrieve_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(methods_router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(evaluation_router, prefix="/api")
