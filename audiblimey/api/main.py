"""FastAPI application for audiblimey."""

import logging
from fastapi import FastAPI
from audiblimey.api.routes.embeddings import router as embeddings_router
from audiblimey.api.routes.imports import router as imports_router
from audiblimey.api.routes.library import router as library_router
from audiblimey.api.routes.recommendations import router as recommendations_router
from audiblimey.api.routes.sync import router as sync_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="audiblimey",
    description="Audiobook recommendation engine powered by Audible + Goodreads taste fusion",
    version="0.1.0",
)

app.include_router(embeddings_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
app.include_router(library_router, prefix="/api")
app.include_router(recommendations_router, prefix="/api")
app.include_router(sync_router, prefix="/api")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "audiblimey"}
