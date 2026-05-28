import time
from dataclasses import dataclass, field
import asyncio

@dataclass
class MetricsStore:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_leads_scraped: int = 0
    total_execution_time: float = 0.0
    active_scrapes: int = 0
    start_time: float = field(default_factory=time.time)

    def record_request(self, success: bool, leads: int, duration: float):
        self.total_requests += 1
        if success: self.successful_requests += 1
        else: self.failed_requests += 1
        self.total_leads_scraped += leads
        self.total_execution_time += duration

    @property
    def avg_execution_time(self) -> float:
        if self.successful_requests == 0: return 0.0
        return round(self.total_execution_time / self.successful_requests, 2)

    @property
    def uptime_seconds(self) -> float:
        return round(time.time() - self.start_time, 2)

    def to_dict(self):
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "total_leads_scraped": self.total_leads_scraped,
            "avg_execution_time_seconds": self.avg_execution_time,
            "active_scrapes": self.active_scrapes,
            "uptime_seconds": self.uptime_seconds,
        }

metrics = MetricsStore()
