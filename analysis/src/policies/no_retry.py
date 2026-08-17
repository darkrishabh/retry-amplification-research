"""No retry policy - baseline without retries."""

from .base import RetryPolicy, RetryDecision, RetryContext


class NoRetryPolicy(RetryPolicy):
    """
    Baseline policy that never retries.
    
    Used as a control to measure the benefit of retry policies.
    """
    
    def __init__(self):
        super().__init__("NoRetry")
    
    def should_retry(self, context: RetryContext) -> RetryDecision:
        """Never retry."""
        return RetryDecision.NO_RETRY
    
    def get_retry_delay(self, attempt_number: int) -> float:
        """No delay needed since we don't retry."""
        return 0.0
