from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
import uuid


class ScrapeRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=200)
    max_results: int = Field(default=50, ge=1, le=1000)
    language: str = Field(default="en")
    extract_details: bool = Field(default=True)
    webhook_url: Optional[str] = Field(default=None, description="POST results here when done")

    @field_validator("query")
    @classmethod
    def clean(cls, v): return v.strip()


class BusinessLead(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    reviews_count: Optional[int] = Field(default=None, ge=0)
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    place_id: Optional[str] = None
    opening_hours: Optional[List[str]] = None
    is_open_now: Optional[bool] = None
    images: Optional[List[str]] = Field(default=None)
    services: Optional[List[str]] = None
    amenities: Optional[List[str]] = None
    social_links: Optional[Dict[str, str]] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    data_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def score(self):
        fields = [self.name, self.phone, self.website, self.address,
                  self.rating, self.category, self.latitude, self.email,
                  self.opening_hours, self.description]
        self.data_quality_score = round(sum(1 for f in fields if f is not None) / len(fields), 2)
        return self


# ── Sync response ─────────────────────────────────────────────────────────────
class ScrapeResponse(BaseModel):
    success: bool
    query: str
    total_results: int
    execution_time: str
    data: List[BusinessLead]
    errors: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


# ── Async job system ──────────────────────────────────────────────────────────
JobStatus = Literal["queued", "running", "completed", "failed"]

class JobCreateRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=200)
    max_results: int = Field(default=100, ge=1, le=1000)
    extract_details: bool = True
    webhook_url: Optional[str] = None

    @field_validator("query")
    @classmethod
    def clean(cls, v): return v.strip()

class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    query: str
    max_results: int
    progress: int = Field(default=0, ge=0, le=100)   # percentage
    results_so_far: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time: Optional[str] = None
    error: Optional[str] = None
    download_url: Optional[str] = None

class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    query: str
    total_results: int
    execution_time: Optional[str]
    data: List[BusinessLead]
    errors: List[str] = Field(default_factory=list)


# ── Health / Metrics ──────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    version: str = "2.0.0"
    uptime_seconds: float
    browser_pool: Dict[str, Any]
    active_jobs: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class MetricsResponse(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_leads_scraped: int
    avg_execution_time_seconds: float
    browser_pool_size: int
    active_scrapes: int
    uptime_seconds: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
