"""Request model for the simulation."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid


class RequestStatus(Enum):
    """Status of a request."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REJECTED = "rejected"  # Load shedding


@dataclass
class Request:
    """Represents a single request in the system."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    origin_time: float = 0.0
    source_service: Optional[str] = None
    target_service: Optional[str] = None
    
    # Retry tracking
    attempt_number: int = 1
    original_request_id: Optional[str] = None  # For tracking retries
    is_retry: bool = False
    
    # Timing
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    queue_time: float = 0.0
    processing_time: float = 0.0
    
    # Status
    status: RequestStatus = RequestStatus.PENDING
    error_message: Optional[str] = None
    
    # Downstream tracking
    downstream_requests: list = field(default_factory=list)
    downstream_latency: float = 0.0
    
    @property
    def total_latency(self) -> float:
        """Total end-to-end latency."""
        if self.start_time is None or self.end_time is None:
            return 0.0
        return self.end_time - self.start_time
    
    @property
    def is_terminal(self) -> bool:
        """Check if request has reached a terminal state."""
        return self.status in (
            RequestStatus.SUCCESS,
            RequestStatus.FAILED,
            RequestStatus.TIMEOUT,
            RequestStatus.REJECTED,
        )
    
    def create_retry(self, attempt: int) -> "Request":
        """Create a retry request based on this request."""
        return Request(
            origin_time=self.origin_time,
            source_service=self.source_service,
            target_service=self.target_service,
            attempt_number=attempt,
            original_request_id=self.original_request_id or self.id,
            is_retry=True,
        )
    
    def __repr__(self) -> str:
        retry_info = f" (retry #{self.attempt_number})" if self.is_retry else ""
        return f"Request({self.id}{retry_info}, {self.status.value})"
