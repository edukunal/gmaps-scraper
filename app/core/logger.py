import structlog, logging, sys
from app.config import settings

def configure_logging():
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    processors = shared + ([structlog.dev.ConsoleRenderer(colors=True)] if settings.DEBUG else [structlog.processors.JSONRenderer()])
    structlog.configure(processors=processors, wrapper_class=structlog.make_filtering_bound_logger(level),
                        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout), cache_logger_on_first_use=True)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for lib in ("playwright","asyncio","urllib3","httpx"):
        logging.getLogger(lib).setLevel(logging.WARNING)

def get_logger(name: str = __name__):
    return structlog.get_logger(name)
