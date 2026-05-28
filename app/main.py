from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.logger import configure_logging, get_logger
from app.core.browser_manager import browser_pool
from app.core.job_manager import job_manager
from app.api.routes import router
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.models.schemas import ErrorResponse

configure_logging()
log = get_logger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting", host=settings.HOST, port=settings.PORT)
    await browser_pool.initialize()
    job_manager.start()
    log.info("Ready — docs at /docs")
    yield
    log.info("Shutting down")
    await job_manager.stop()
    await browser_pool.shutdown()

app = FastAPI(
    title="🗺️ Google Maps Lead Scraper API",
    description="""
**God-tier async lead scraping API.**

## Endpoints
| | |
|---|---|
| `POST /scrape` | Synchronous — waits, returns results |
| `POST /jobs` | Async — returns job_id immediately |
| `GET /jobs/{id}/stream` | SSE live stream as leads found |
| `GET /jobs/{id}/export?format=csv` | Download CSV |
| `GET /jobs/{id}/export?format=xlsx` | Download Excel |
| `GET /health` | Pool + system status |
| `GET /metrics` | Scraping statistics |
""",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

@app.exception_handler(Exception)
async def global_exc(request: Request, exc: Exception):
    log.error("Unhandled", path=request.url.path, error=str(exc))
    return JSONResponse(500, content=ErrorResponse(error="Internal error", detail=str(exc)).model_dump(mode="json"))

@app.get("/", include_in_schema=False)
async def root():
    return {"service":"Google Maps Lead Scraper","version":"2.0.0","docs":"/docs"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, workers=1, log_level="info", access_log=False)
