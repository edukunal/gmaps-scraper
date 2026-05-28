import time, uuid, structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = str(uuid.uuid4())[:8]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        start = time.time()
        response: Response = await call_next(request)
        ms = round((time.time()-start)*1000,2)
        structlog.get_logger("http").info("req", method=request.method, path=request.url.path, status=response.status_code, ms=ms)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time"] = f"{ms}ms"
        return response
