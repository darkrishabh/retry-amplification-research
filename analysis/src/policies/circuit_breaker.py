"""Circuit breaker retry policy."""

from enum import Enum
from typing import Optional

from .base import RetryPolicy, RetryDecision, RetryContext
from .standard_retry import StandardRetryPolicy


class CircuitState(Enum):
    """State of the circuit breaker."""
    CLOSED = "closed"      # Normal operation, requests flow through
    OPEN = "open"          # Failures exceeded threshold, requests blocked
    HALF_OPEN = "half_open"  # Testing if service has recovered


class CircuitBreakerPolicy(RetryPolicy):
    """
    Circuit breaker pattern combined with retry logic.
    
    The circuit breaker tracks failure rates and stops sending requests
    to a failing service to allow it to recover.
    
    States:
    - CLOSED: Normal operation, retries allowed
    - OPEN: Too many failures, all requests immediately fail
    - HALF_OPEN: Testing recovery, limited requests allowed
    
    Parameters:
        failure_threshold: Failure rate to trip the circuit (0.0 to 1.0)
        recovery_timeout: Time to wait before testing recovery (seconds)
        half_open_max_requests: Requests allowed in half-open state
        underlying_policy: Retry policy to use when circuit is closed
    """
    
    def __init__(
        self,
        failure_threshold: float = 0.5,
        recovery_timeout: float = 30.0,
        half_open_max_requests: int = 3,
        underlying_policy: Optional[StandardRetryPolicy] = None,
    ):
        super().__init__("CircuitBreaker")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_requests = half_open_max_requests
        self.underlying_policy = underlying_policy or StandardRetryPolicy()
        
        # State
        self.state = CircuitState.CLOSED
        self.last_failure_time: Optional[float] = None
        self.last_state_change_time: float = 0.0
        
        # Tracking
        self._recent_requests: int = 0
        self._recent_failures: int = 0
        self._half_open_requests: int = 0
        self._window_size: int = 100  # Requests to track for failure rate
    
    @property
    def failure_rate(self) -> float:
        """Current failure rate in the tracking window."""
        if self._recent_requests == 0:
            return 0.0
        return self._recent_failures / self._recent_requests
    
    def _check_state_transition(self, current_time: float) -> None:
        """Check if circuit state should transition."""
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time and current_time - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change_time = current_time
                self._half_open_requests = 0
        
        elif self.state == CircuitState.CLOSED:
            # Check if failure threshold exceeded
            if self._recent_requests >= 10 and self.failure_rate >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.last_failure_time = current_time
                self.last_state_change_time = current_time
    
    def should_retry(self, context: RetryContext) -> RetryDecision:
        """
        Determine if retry should be attempted based on circuit state.
        """
        self._check_state_transition(context.current_time)
        
        if self.state == CircuitState.OPEN:
            return RetryDecision.CIRCUIT_OPEN
        
        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_requests >= self.half_open_max_requests:
                return RetryDecision.CIRCUIT_OPEN
            self._half_open_requests += 1
        
        # Delegate to underlying policy
        return self.underlying_policy.should_retry(context)
    
    def get_retry_delay(self, attempt_number: int) -> float:
        """Delegate delay calculation to underlying policy."""
        return self.underlying_policy.get_retry_delay(attempt_number)
    
    def on_request_complete(self, request, was_retry: bool) -> None:
        """Update circuit breaker state based on request outcome."""
        super().on_request_complete(request, was_retry)
        
        self._recent_requests += 1
        if request.status.value == "failed":
            self._recent_failures += 1
            self.last_failure_time = request.end_time
        
        # Reset tracking window if it gets too large
        if self._recent_requests > self._window_size:
            self._recent_requests = self._recent_requests // 2
            self._recent_failures = self._recent_failures // 2
        
        # Handle half-open state transitions
        if self.state == CircuitState.HALF_OPEN:
            if request.status.value == "success":
                # Success in half-open, close the circuit
                self.state = CircuitState.CLOSED
                self._recent_requests = 0
                self._recent_failures = 0
            elif request.status.value == "failed":
                # Failure in half-open, reopen the circuit
                self.state = CircuitState.OPEN
    
    def reset(self) -> None:
        """Reset circuit breaker to initial state."""
        super().reset()
        self.state = CircuitState.CLOSED
        self.last_failure_time = None
        self._recent_requests = 0
        self._recent_failures = 0
        self._half_open_requests = 0
        self.underlying_policy.reset()
    
    def __repr__(self) -> str:
        return f"CircuitBreakerPolicy(state={self.state.value}, failure_rate={self.failure_rate:.2f})"
