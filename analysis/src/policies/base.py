"""Base retry policy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.models.request import Request


class RetryDecision(Enum):
    """Decision on whether to retry a request."""
    RETRY = "retry"
    NO_RETRY = "no_retry"
    CIRCUIT_OPEN = "circuit_open"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class RetryContext:
    """Context for making retry decisions."""
    request: Request
    attempt_number: int
    error_type: Optional[str] = None
    downstream_backpressure: float = 0.0
    current_failure_rate: float = 0.0
    current_time: float = 0.0


class RetryPolicy(ABC):
    """
    Abstract base class for retry policies.
    
    Implementations must provide:
    - should_retry(): Determine if a failed request should be retried
    - get_retry_delay(): Calculate delay before next retry attempt
    - on_request_complete(): Update internal state after request completes
    """
    
    def __init__(self, name: str):
        self.name = name
        self._total_retries = 0
        self._successful_retries = 0
        self._failed_retries = 0
    
    @abstractmethod
    def should_retry(self, context: RetryContext) -> RetryDecision:
        """
        Determine if a request should be retried.
        
        Args:
            context: Information about the failed request
            
        Returns:
            RetryDecision indicating whether to retry
        """
        pass
    
    @abstractmethod
    def get_retry_delay(self, attempt_number: int) -> float:
        """
        Calculate the delay before the next retry attempt.
        
        Args:
            attempt_number: The upcoming attempt number (2 for first retry, etc.)
            
        Returns:
            Delay in seconds
        """
        pass
    
    def on_request_complete(self, request: Request, was_retry: bool) -> None:
        """
        Called when a request completes (success or final failure).
        
        Override to update internal state.
        """
        if was_retry:
            self._total_retries += 1
            if request.status.value == "success":
                self._successful_retries += 1
            else:
                self._failed_retries += 1
    
    def on_backpressure(self, signal: float) -> None:
        """
        React to backpressure signal from downstream.
        
        Override to implement backpressure-aware retry logic.
        
        Args:
            signal: Backpressure level (0.0 = healthy, 1.0 = fully overloaded)
        """
        pass
    
    def reset(self) -> None:
        """Reset internal state."""
        self._total_retries = 0
        self._successful_retries = 0
        self._failed_retries = 0
    
    @property
    def retry_success_rate(self) -> float:
        """Success rate of retry attempts."""
        if self._total_retries == 0:
            return 0.0
        return self._successful_retries / self._total_retries
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"
