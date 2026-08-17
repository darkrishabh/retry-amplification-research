"""SimPy-based simulation engine for retry amplification experiments."""

from dataclasses import dataclass
from typing import Optional
import random

import simpy

from src.models.topology import Topology
from src.models.request import Request, RequestStatus
from src.models.service import Service
from src.policies.base import RetryPolicy, RetryContext, RetryDecision
from src.policies.no_retry import NoRetryPolicy
from .scenarios import FailureScenario
from .metrics import MetricsCollector, ExperimentResult


@dataclass
class SimulationConfig:
    """Configuration for a simulation run."""
    
    # Topology configuration
    num_tiers: int = 5
    service_capacity: float = 1000.0  # requests per second per service
    base_processing_time: float = 0.01  # 10ms
    max_queue_size: int = 1000
    
    # Load configuration
    base_load: float = 500.0  # requests per second (50% utilization)
    
    # Timing
    warmup_duration: float = 10.0  # seconds to stabilize before scenario
    scenario_duration: float = 30.0  # duration of failure scenario
    cooldown_duration: float = 60.0  # seconds after scenario to observe recovery
    
    # Metrics
    sample_interval: float = 0.5  # How often to sample metrics
    
    # Random seed for reproducibility
    seed: Optional[int] = None
    
    @property
    def total_duration(self) -> float:
        """Total simulation duration."""
        return self.warmup_duration + self.scenario_duration + self.cooldown_duration


class SimulationEngine:
    """
    Discrete-event simulation engine using SimPy.
    
    Simulates a multi-tier service architecture with:
    - Configurable request load
    - Failure injection via scenarios
    - Retry policies
    - Metrics collection
    """
    
    def __init__(
        self,
        config: SimulationConfig,
        retry_policy: RetryPolicy,
        scenario: FailureScenario,
    ):
        self.config = config
        self.retry_policy = retry_policy
        self.scenario = scenario
        
        # Set random seed
        if config.seed is not None:
            random.seed(config.seed)
        
        # Create SimPy environment
        self.env = simpy.Environment()
        
        # Create topology
        tier_names = ["API", "Auth", "Catalog", "Inventory", "Database"][:config.num_tiers]
        self.topology = Topology.create_linear_chain(
            env=self.env,
            num_tiers=config.num_tiers,
            capacity=config.service_capacity,
            base_processing_time=config.base_processing_time,
            tier_names=tier_names,
        )
        
        # Apply failure scenario
        self.scenario.apply_to_topology(self.topology.services)
        
        # Initialize metrics collector
        self.metrics = MetricsCollector(self.topology, config.base_load)
        
        # Tracking
        self._pending_requests: list = []
    
    def _generate_load(self):
        """Generate incoming requests at the configured load rate."""
        entry_service = self.topology.get_entry_service()
        if not entry_service:
            return
        
        inter_arrival_time = 1.0 / self.config.base_load
        
        while True:
            # Create new request
            request = Request(
                origin_time=self.env.now,
                target_service=entry_service.name,
            )
            
            # Start request processing
            self.env.process(self._process_request_with_retry(request, entry_service))
            
            # Wait for next request (Poisson arrival)
            wait_time = random.expovariate(1.0 / inter_arrival_time)
            yield self.env.timeout(wait_time)
    
    def _process_request_with_retry(self, request: Request, service: Service):
        """
        Process a request with retry logic.
        
        Implements the retry loop with policy-based decisions.
        """
        current_request = request
        attempt = 1
        max_total_attempts = 10  # Safety limit
        
        while attempt <= max_total_attempts:
            # Try to process the request
            if not service.accept_request(current_request):
                # Request rejected (load shedding)
                self.metrics.record_request(current_request, self.env.now)
                break
            
            # Process through the service
            yield from service.process_request(current_request)
            
            # Record the completed request
            self.metrics.record_request(current_request, self.env.now)
            
            # Update policy state
            self.retry_policy.on_request_complete(current_request, was_retry=current_request.is_retry)
            
            # Check if we should retry
            if current_request.status == RequestStatus.SUCCESS:
                # Success - we're done
                break
            
            # Request failed - check retry policy
            attempt += 1
            context = RetryContext(
                request=current_request,
                attempt_number=attempt,
                error_type=current_request.error_message,
                downstream_backpressure=service.backpressure_signal,
                current_failure_rate=service.metrics.failure_rate,
                current_time=self.env.now,
            )
            
            # Get downstream backpressure for ARB
            if service.downstream_services:
                downstream_bp = max(
                    ds.backpressure_signal for ds in service.downstream_services
                )
                self.retry_policy.on_backpressure(downstream_bp)
            
            decision = self.retry_policy.should_retry(context)
            
            if decision != RetryDecision.RETRY:
                # No retry - request fails
                break
            
            # Wait before retrying
            delay = self.retry_policy.get_retry_delay(attempt)
            if delay > 0:
                yield self.env.timeout(delay)
            
            # Create retry request
            current_request = request.create_retry(attempt)
    
    def _collect_metrics(self):
        """Periodically collect metrics."""
        while True:
            yield self.env.timeout(self.config.sample_interval)
            self.metrics.sample_metrics(self.env.now)
            
            # Check for recovery after failure ends
            failure_end = self.config.warmup_duration + self.config.scenario_duration
            if self.env.now > failure_end:
                self.metrics.mark_failure_end(failure_end)
                self.metrics.check_recovery(self.env.now)
    
    def run(self, trial_number: int = 1) -> ExperimentResult:
        """
        Run the simulation and return results.
        
        Args:
            trial_number: Trial number for this run
            
        Returns:
            ExperimentResult with all collected metrics
        """
        # Reset state
        self.topology.reset_all_metrics()
        self.metrics.reset()
        self.retry_policy.reset()
        
        # Start processes
        self.env.process(self._generate_load())
        self.env.process(self._collect_metrics())
        
        # Run simulation
        self.env.run(until=self.config.total_duration)
        
        # Generate results
        return self.metrics.get_result(
            scenario_name=self.scenario.name,
            policy_name=self.retry_policy.name,
            trial_number=trial_number,
            simulation_duration=self.config.total_duration,
        )


def run_experiment(
    policy: RetryPolicy,
    scenario: FailureScenario,
    config: Optional[SimulationConfig] = None,
    num_trials: int = 100,
    seed: Optional[int] = None,
) -> list[ExperimentResult]:
    """
    Run a complete experiment with multiple trials.
    
    Args:
        policy: Retry policy to test
        scenario: Failure scenario to inject
        config: Simulation configuration
        num_trials: Number of trials to run
        seed: Base random seed (each trial uses seed + trial_number)
        
    Returns:
        List of ExperimentResult for each trial
    """
    if config is None:
        config = SimulationConfig()
    
    results = []
    
    for trial in range(num_trials):
        # Set seed for reproducibility
        trial_config = SimulationConfig(
            num_tiers=config.num_tiers,
            service_capacity=config.service_capacity,
            base_processing_time=config.base_processing_time,
            max_queue_size=config.max_queue_size,
            base_load=config.base_load,
            warmup_duration=config.warmup_duration,
            scenario_duration=config.scenario_duration,
            cooldown_duration=config.cooldown_duration,
            sample_interval=config.sample_interval,
            seed=seed + trial if seed is not None else None,
        )
        
        engine = SimulationEngine(trial_config, policy, scenario)
        result = engine.run(trial_number=trial + 1)
        results.append(result)
    
    return results


def aggregate_results(results: list[ExperimentResult]) -> dict:
    """
    Aggregate results from multiple trials.
    
    Calculates means, standard deviations, and confidence intervals.
    """
    import statistics
    
    n = len(results)
    if n == 0:
        return {}
    
    # Cascade probability
    cascade_count = sum(1 for r in results if r.cascade_occurred)
    cascade_prob = cascade_count / n
    
    # RAF statistics
    rafs = [r.raf for r in results]
    raf_mean = statistics.mean(rafs)
    raf_std = statistics.stdev(rafs) if n > 1 else 0
    
    # Success rate
    success_rates = [r.success_rate for r in results]
    success_mean = statistics.mean(success_rates)
    success_std = statistics.stdev(success_rates) if n > 1 else 0
    
    # Recovery time (only for trials that recovered)
    recovery_times = [r.recovery_time for r in results if r.recovery_time is not None]
    recovery_mean = statistics.mean(recovery_times) if recovery_times else None
    
    # 95% confidence interval
    z = 1.96
    raf_ci = z * raf_std / (n ** 0.5) if n > 1 else 0
    success_ci = z * success_std / (n ** 0.5) if n > 1 else 0
    cascade_ci = z * ((cascade_prob * (1 - cascade_prob) / n) ** 0.5)
    
    return {
        "scenario": results[0].scenario_name,
        "policy": results[0].policy_name,
        "num_trials": n,
        "cascade_probability": cascade_prob,
        "cascade_ci": cascade_ci,
        "raf_mean": raf_mean,
        "raf_ci": raf_ci,
        "success_rate_mean": success_mean,
        "success_rate_ci": success_ci,
        "recovery_time_mean": recovery_mean,
    }
