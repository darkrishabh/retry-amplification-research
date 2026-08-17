"""Adaptive Retry Budgeting (ARB) policy - the main contribution of the paper."""

import random
from typing import Optional
from collections import deque

from .base import RetryPolicy, RetryDecision, RetryContext


class AdaptiveRetryBudgetingPolicy(RetryPolicy):
    """
    Adaptive Retry Budgeting (ARB) - A coordinated retry strategy.
    
    ARB introduces a retry budget concept that dynamically adjusts based on:
    1. Observed failure rates
    2. Downstream backpressure signals
    3. System-wide health indicators
    
    This prevents retry amplification by limiting total retry capacity
    and responding to overload conditions.
    
    Parameters:
        alpha: Budget increase rate when healthy (default 0.1)
        beta: Budget decrease rate when stressed (default 0.5)
        theta_high: High failure threshold to trigger budget decrease (default 0.3)
        theta_low: Low failure threshold to allow budget increase (default 0.05)
        initial_budget: Starting retry budget (0.0 to 1.0)
        adjustment_interval: How often to adjust budget in seconds
        base_load: Expected baseline load for budget calculations
        max_retries: Maximum retry attempts per request
        base_delay: Base delay for exponential backoff
    """
    
    def __init__(
        self,
        alpha: float = 0.1,
        beta: float = 0.5,
        theta_high: float = 0.3,
        theta_low: float = 0.05,
        initial_budget: float = 1.0,
        adjustment_interval: float = 1.0,
        base_load: float = 500.0,
        max_retries: int = 3,
        base_delay: float = 0.1,
    ):
        super().__init__("AdaptiveRetryBudgeting")
        
        # ARB parameters
        self.alpha = alpha
        self.beta = beta
        self.theta_high = theta_high
        self.theta_low = theta_low
        self.base_load = base_load
        self.max_retries = max_retries
        self.base_delay = base_delay
        
        # State
        self.retry_budget = initial_budget
        self.initial_budget = initial_budget
        self.adjustment_interval = adjustment_interval
        self.last_adjustment_time = 0.0
        
        # Backpressure tracking
        self.downstream_backpressure = 0.0
        self.is_downstream_overloaded = False
        
        # Failure rate tracking (sliding window)
        self._failure_window: deque = deque(maxlen=100)
        self._request_window: deque = deque(maxlen=100)
        
        # Metrics for analysis
        self.budget_history: list = []  # (time, budget) tuples
        self.retry_decisions: list = []  # Track decisions for analysis
        
        # Current retry tokens available
        self._tokens_available = base_load * initial_budget
    
    @property
    def current_failure_rate(self) -> float:
        """Calculate failure rate over sliding window."""
        if len(self._request_window) == 0:
            return 0.0
        return sum(self._failure_window) / len(self._request_window)
    
    def _adjust_budget(self, current_time: float) -> None:
        """
        Periodically adjust retry budget based on system state.
        
        This implements the budget adjustment algorithm from the paper.
        """
        if current_time - self.last_adjustment_time < self.adjustment_interval:
            return
        
        self.last_adjustment_time = current_time
        old_budget = self.retry_budget
        
        # Check conditions for budget adjustment
        if self.current_failure_rate > self.theta_high or self.is_downstream_overloaded:
            # Decrease budget multiplicatively (fast decrease)
            self.retry_budget = self.retry_budget * (1 - self.beta)
        elif self.current_failure_rate < self.theta_low:
            # Increase budget additively (slow increase)
            self.retry_budget = min(1.0, self.retry_budget + self.alpha)
        
        # Update available tokens
        self._tokens_available = self.base_load * self.retry_budget
        
        # Record for analysis
        self.budget_history.append((current_time, self.retry_budget))
    
    def should_retry(self, context: RetryContext) -> RetryDecision:
        """
        Determine if retry should be attempted based on budget and system state.
        
        Implements the probabilistic retry decision from the paper:
        - Check if budget allows retry
        - Check downstream backpressure
        - Use probabilistic decision based on budget and failure rate
        """
        # First, adjust budget if needed
        self._adjust_budget(context.current_time)
        
        # Check max retry limit
        if context.attempt_number > self.max_retries:
            self.retry_decisions.append(("max_retries", context.current_time))
            return RetryDecision.NO_RETRY
        
        # Check if downstream is overloaded
        if self.is_downstream_overloaded:
            self.retry_decisions.append(("backpressure", context.current_time))
            return RetryDecision.NO_RETRY
        
        # Check if budget allows retry
        if self.retry_budget <= 0 or self._tokens_available <= 0:
            self.retry_decisions.append(("budget_exhausted", context.current_time))
            return RetryDecision.BUDGET_EXHAUSTED
        
        # Probabilistic retry based on budget and failure rate
        # Higher failure rate = lower retry probability (avoid amplification)
        retry_probability = min(self.retry_budget, 1 - self.current_failure_rate)
        
        if random.random() < retry_probability:
            # Consume a token
            self._tokens_available -= 1
            self.retry_decisions.append(("retry", context.current_time))
            return RetryDecision.RETRY
        else:
            self.retry_decisions.append(("probabilistic_skip", context.current_time))
            return RetryDecision.NO_RETRY
    
    def get_retry_delay(self, attempt_number: int) -> float:
        """
        Calculate retry delay with exponential backoff and jitter.
        
        ARB uses standard exponential backoff to spread out retry load.
        """
        delay = self.base_delay * (2 ** (attempt_number - 1))
        # Add jitter (±25%)
        jitter = delay * 0.25 * (random.random() * 2 - 1)
        return max(0, delay + jitter)
    
    def on_request_complete(self, request, was_retry: bool) -> None:
        """Update failure tracking based on request outcome."""
        super().on_request_complete(request, was_retry)
        
        # Update sliding window
        self._request_window.append(1)
        self._failure_window.append(1 if request.status.value == "failed" else 0)
    
    def on_backpressure(self, signal: float) -> None:
        """
        React to backpressure signal from downstream services.
        
        This is critical for preventing retry amplification.
        When downstream services signal overload, ARB immediately
        reduces retry attempts.
        """
        self.downstream_backpressure = signal
        self.is_downstream_overloaded = signal > 0.8
        
        # Immediate budget reduction on strong backpressure
        if signal > 0.9:
            self.retry_budget *= 0.5
            self._tokens_available = self.base_load * self.retry_budget
    
    def reset(self) -> None:
        """Reset ARB state."""
        super().reset()
        self.retry_budget = self.initial_budget
        self._tokens_available = self.base_load * self.initial_budget
        self.downstream_backpressure = 0.0
        self.is_downstream_overloaded = False
        self.last_adjustment_time = 0.0
        self._failure_window.clear()
        self._request_window.clear()
        self.budget_history.clear()
        self.retry_decisions.clear()
    
    def get_metrics(self) -> dict:
        """Get ARB-specific metrics for analysis."""
        decision_counts = {}
        for decision, _ in self.retry_decisions:
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
        
        return {
            "final_budget": self.retry_budget,
            "current_failure_rate": self.current_failure_rate,
            "decision_counts": decision_counts,
            "budget_adjustments": len(self.budget_history),
            "total_retry_decisions": len(self.retry_decisions),
        }
    
    def __repr__(self) -> str:
        return (
            f"AdaptiveRetryBudgetingPolicy("
            f"budget={self.retry_budget:.2f}, "
            f"failure_rate={self.current_failure_rate:.2f}, "
            f"backpressure={self.downstream_backpressure:.2f})"
        )
