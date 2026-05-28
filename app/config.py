from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    PORT: int = int(os.getenv("PORT", 8000))
    HOST: str = "0.0.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    WORKERS: int = 1

    # Browser pool
    BROWSER_POOL_SIZE: int = int(os.getenv("BROWSER_POOL_SIZE", 3))
    DETAIL_TAB_CONCURRENCY: int = int(os.getenv("DETAIL_TAB_CONCURRENCY", 5))  # parallel tabs per scrape
    MAX_CONCURRENT_SCRAPES: int = int(os.getenv("MAX_CONCURRENT_SCRAPES", 3))
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

    # Timeouts
    PAGE_TIMEOUT: int = 30_000
    NAVIGATION_TIMEOUT: int = 45_000
    ELEMENT_TIMEOUT: int = 12_000
    DETAIL_TIMEOUT: int = 6_000

    # Scroll
    SCROLL_PAUSE_MIN: float = 0.20
    SCROLL_PAUSE_MAX: float = 0.55
    SCROLL_ATTEMPTS_MAX: int = 100

    # Retry
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 1.2
    RETRY_BACKOFF: float = 1.5

    # Proxy
    PROXY_URL: Optional[str] = os.getenv("PROXY_URL")
    PROXY_USERNAME: Optional[str] = os.getenv("PROXY_USERNAME")
    PROXY_PASSWORD: Optional[str] = os.getenv("PROXY_PASSWORD")

    # Limits
    DEFAULT_MAX_RESULTS: int = 100
    HARD_MAX_RESULTS: int = 1000

    # Jobs
    JOB_MAX_AGE_SECONDS: int = 3600       # purge jobs after 1h
    JOB_RESULT_RETENTION: int = 500       # keep last N completed jobs in memory

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
