from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import prices

app = FastAPI(title="Price Checker", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prices.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "cache_dir": settings.cache_dir, "cache_ttl_hours": settings.cache_ttl_hours}


# Serve the frontend. Must come after API routes.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
