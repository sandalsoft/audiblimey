"""FastAPI application for audiblimey."""

import logging
from fastapi import FastAPI
from audiblimey.api.routes.imports import router as imports_router
from audiblimey.api.routes.recommendations import router as recommendations_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="audiblimey",
    description="Audiobook recommendation engine powered by Audible + Goodreads taste fusion",
    version="0.1.0",
)

app.include_router(imports_router, prefix="/api")
app.include_router(recommendations_router, prefix="/api")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "audiblimey"}
