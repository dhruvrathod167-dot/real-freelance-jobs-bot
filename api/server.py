"""
FastAPI Server & Health Monitoring
Provides RESTful endpoints for container health checks,
deployment liveness/readiness probes, and platform metrics.
"""

from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.db import get_db_session
from database.crud import get_system_stats
from utils.logger import logger

app = FastAPI(
    title="Real Freelance Jobs API",
    description="Automated risk-screening and verification engine for legitimate freelance opportunities.",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Service status information."""
    return {
        "service": "Real Freelance Jobs Bot & Verification API",
        "bot_username": settings.BOT_USERNAME,
        "environment": settings.ENVIRONMENT,
        "status": "online"
    }


@app.get("/health")
async def health_check():
    """Liveness and readiness probe for Render, Railway, Kubernetes, or Docker."""
    db_status = "healthy"
    try:
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error(f"Database health check failed: {exc}")
        db_status = "unhealthy"

    status_code = 200 if db_status == "healthy" else 503
    return JSONResponse(
        content={
            "status": "ok" if db_status == "healthy" else "degraded",
            "database": db_status,
            "bot_username": settings.BOT_USERNAME,
            "ai_provider": settings.effective_ai_provider,
            "ai_configured": bool(settings.AI_API_KEY),
        },
        status_code=status_code
    )


@app.get("/api/stats")
async def api_stats():
    """Returns community statistics."""
    try:
        async with get_db_session() as session:
            stats = await get_system_stats(session)
        return {"status": "success", "data": stats}
    except Exception as exc:
        logger.error(f"Failed to fetch stats: {exc}")
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)
