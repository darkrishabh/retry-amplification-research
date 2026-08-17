"""Standard retry policy with exponential backoff and jitter."""

import random
from typing import Optional

from .base import RetryPolicy, RetryDecision, RetryContext


class StandardRetryPolicy(RetryPolicy):
    """
    Standard retry policy implementing exponential backoff with optional jitter.
    
    This is the most common retry implementation found in production systems.
    
    Parameters:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay before first retry (seconds)
        max_delay: Maximum delay cap (seconds)
        exponential_base: Base for exponential backoff (typically 2)
        jitter: Whether to add randomization to delays
        jitter_factor: Maximum jitter as fraction of delay (0.0 to 1.0)
        retry_on_all_errors: Whether to retry on all errors (anti-pattern)
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.1,  # 100ms
        max_delay: float = 10.0,  # 10 seconds
        exponential_base: float = 2.0,
        jitter: bool = True,
        jitter_factor: float = 0.5,
        retry_on_all_errors: bool = False,
    ):
        super().__init__("StandardRetry")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.jitter_factor = jitter_factor
        self.retry_on_all_errors = retry_on_all_errors
    
    def should_retry(self, context: RetryContext) -> RetryDecision:
        """
        Determine if request should be retried based on attempt count and error type.
        """
        # Check retry limit
        if context.attempt_number > self.max_retries:
            return RetryDecision.NO_RETRY
        
        # Check error type (simplified - in reality would check specific error codes)
        if not self.retry_on_all_errors:
            # Don't retry on client errors (4xx) - these are non-transient
            if context.error_type and context.error_type.startswith("4"):
                return RetryDecision.NO_RETRY
        
        return RetryDecision.RETRY
    
    def get_retry_delay(self, attempt_number: int) -> float:
        """
        Calculate exponential backoff delay with optional jitter.
        
        Formula: min(base_delay * (exponential_base ^ (attempt - 1)), max_delay) * (1 + jitter)
        """
        # Calculate base exponential delay
        delay = self.base_delay * (self.exponential_base ** (attempt_number - 1))
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter if enabled
        if self.jitter:
            jitter_amount = delay * self.jitter_factor * random.random()
            delay += jitter_amount
        
        return delay


class AggressiveRetryPolicy(StandardRetryPolicy):
    """
    Anti-pattern: Aggressive retry with high count and no backoff.
    
    This demonstrates the "Aggressive Retry" anti-pattern from the paper.
    """
    
    def __init__(self, max_retries: int = 5):
        super().__init__(
            max_retries=max_retries,
            base_delay=0.01,  # 10ms - very short
            max_delay=0.1,
            exponential_base=1.0,  # No exponential increase
            jitter=False,  # No jitter
            retry_on_all_errors=True,  # Retry everything
        )
        self.name = "AggressiveRetry"


class ImmediateRetryPolicy(StandardRetryPolicy):
    """
    Anti-pattern: Immediate retry with no backoff.
    
    This demonstrates the "No Backoff" anti-pattern.
    """
    
    def __init__(self, max_retries: int = 3):
        super().__init__(
            max_retries=max_retries,
            base_delay=0.0,  # No delay
            max_delay=0.0,
            jitter=False,
        )
        self.name = "ImmediateRetry"
    
    def get_retry_delay(self, attempt_number: int) -> float:
        """No delay - immediate retry."""
        return 0.0
