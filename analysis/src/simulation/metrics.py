"""Metrics collection and analysis for simulation experiments."""

from dataclasses import dataclass, field
from typing import Optional
import statistics

from src.models.topology import Topology


@dataclass
class ExperimentResult:
    """
    Results from a single simulation experiment.
    
    Captures all metrics needed for analysis in the paper.
    """
    
    # Experiment configuration
    scenario_name: str = ""
    policy_name: str = ""
    trial_number: int = 0
    simulation_duration: float = 0.0
    
    # Primary metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    retry_requests: int = 0
    
    # Retry Amplification Factor
    base_load: float = 0.0
    peak_load: float = 0.0
    raf: float = 1.0  # Retry Amplification Factor
    
    # Cascade detection
    cascade_occurred: bool = False
    time_to_cascade: Optional[float] = None
    
    # Recovery
    recovery_time: Optional[float] = None  # Time to return to normal after failure ends
    
    # Success rate
    success_rate: float = 0.0
    
    # Latency
    avg_latency: float = 0.0
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    p99_latency: float = 0.0
    
    # Per-service metrics
    service_metrics: dict = field(default_factory=dict)
    
    # Time series data (for visualization)
    load_over_time: list = field(default_factory=list)
    failure_rate_over_time: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "scenario": self.scenario_name,
            "policy": self.policy_name,
            "trial": self.trial_number,
            "duration": self.simulation_duration,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "rejected_requests": self.rejected_requests,
            "retry_requests": self.retry_requests,
            "base_load": self.base_load,
            "peak_load": self.peak_load,
            "raf": self.raf,
            "cascade_occurred": self.cascade_occurred,
            "time_to_cascade": self.time_to_cascade,
            "recovery_time": self.recovery_time,
            "success_rate": self.success_rate,
            "avg_latency": self.avg_latency,
        }


class MetricsCollector:
    """
    Collects and aggregates metrics during simulation.
    
    Provides methods to calculate:
    - Retry Amplification Factor (RAF)
    - Cascade probability
    - Recovery time
    - Success rates
    """
    
    def __init__(self, topology: Topology, base_load: float = 500.0):
        self.topology = topology
        self.base_load = base_load
        
        # Request tracking
        self.all_requests: list = []
        self.latencies: list = []
        
        # Time series
        self.load_samples: list = []  # (time, load)
        self.failure_samples: list = []  # (time, failure_rate)
        
        # Cascade tracking
        self.cascade_detected = False
        self.cascade_start_time: Optional[float] = None
        self.overload_start_time: Optional[float] = None
        
        # Recovery tracking
        self.failure_end_time: Optional[float] = None
        self.recovery_detected_time: Optional[float] = None
    
    def record_request(self, request, current_time: float) -> None:
        """Record a completed request."""
        self.all_requests.append(request)
        if request.total_latency > 0:
            self.latencies.append(request.total_latency)
    
    def sample_metrics(self, current_time: float) -> None:
        """Take a periodic sample of system metrics."""
        # Get entry service load
        entry = self.topology.get_entry_service()
        if entry:
            self.load_samples.append((current_time, entry.current_load))
            self.failure_samples.append((current_time, entry.metrics.failure_rate))
        
        # Check for cascade
        self._check_cascade(current_time)
    
    def _check_cascade(self, current_time: float) -> None:
        """Check if a cascade has occurred."""
        # Count how many services are overloaded
        overloaded_count = sum(
            1 for s in self.topology.services.values() if s.is_overloaded
        )
        total_services = len(self.topology.services)
        
        # Cascade if majority of services are overloaded
        majority_overloaded = overloaded_count >= (total_services * 0.6)
        
        if majority_overloaded:
            if self.overload_start_time is None:
                self.overload_start_time = current_time
            elif current_time - self.overload_start_time > 10:
                # Majority overloaded for >10 seconds = cascade
                if not self.cascade_detected:
                    self.cascade_detected = True
                    self.cascade_start_time = self.overload_start_time
        else:
            # Reset if recovered
            if self.overload_start_time and current_time - self.overload_start_time < 5:
                self.overload_start_time = None
    
    def mark_failure_end(self, time: float) -> None:
        """Mark when the failure scenario ends."""
        self.failure_end_time = time
    
    def check_recovery(self, current_time: float) -> bool:
        """Check if system has recovered after failure ends."""
        if self.failure_end_time is None or self.recovery_detected_time is not None:
            return False
        
        # Check if all services are below 80% utilization
        all_recovered = all(
            s.utilization < 0.8 for s in self.topology.services.values()
        )
        
        if all_recovered:
            self.recovery_detected_time = current_time
            return True
        
        return False
    
    def calculate_raf(self) -> float:
        """
        Calculate the Retry Amplification Factor.
        
        RAF = Total_Requests_Including_Retries / Original_Requests
        """
        # Count original requests vs total (including retries)
        original_requests = sum(1 for r in self.all_requests if not r.is_retry)
        total_requests = len(self.all_requests)
        
        if original_requests == 0:
            return 1.0
        
        return total_requests / original_requests
    
    def get_result(
        self,
        scenario_name: str,
        policy_name: str,
        trial_number: int,
        simulation_duration: float,
    ) -> ExperimentResult:
        """Generate experiment result from collected metrics."""
        
        # Calculate aggregate metrics
        total = len(self.all_requests)
        successful = sum(1 for r in self.all_requests if r.status.value == "success")
        failed = sum(1 for r in self.all_requests if r.status.value == "failed")
        rejected = sum(1 for r in self.all_requests if r.status.value == "rejected")
        retries = sum(1 for r in self.all_requests if r.is_retry)
        
        # Calculate latency percentiles
        sorted_latencies = sorted(self.latencies) if self.latencies else [0]
        p50 = sorted_latencies[len(sorted_latencies) // 2]
        p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)]
        p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)]
        avg = statistics.mean(self.latencies) if self.latencies else 0
        
        # Calculate recovery time
        recovery_time = None
        if self.failure_end_time and self.recovery_detected_time:
            recovery_time = self.recovery_detected_time - self.failure_end_time
        elif self.failure_end_time and not self.recovery_detected_time:
            recovery_time = simulation_duration  # Did not recover
        
        return ExperimentResult(
            scenario_name=scenario_name,
            policy_name=policy_name,
            trial_number=trial_number,
            simulation_duration=simulation_duration,
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            rejected_requests=rejected,
            retry_requests=retries,
            base_load=self.base_load,
            peak_load=max(s.metrics.peak_load for s in self.topology.services.values()),
            raf=self.calculate_raf(),
            cascade_occurred=self.cascade_detected,
            time_to_cascade=self.cascade_start_time,
            recovery_time=recovery_time,
            success_rate=successful / total if total > 0 else 0,
            avg_latency=avg,
            p50_latency=p50,
            p95_latency=p95,
            p99_latency=p99,
            service_metrics=self.topology.get_aggregate_metrics()["services"],
            load_over_time=self.load_samples.copy(),
            failure_rate_over_time=self.failure_samples.copy(),
        )
    
    def reset(self) -> None:
        """Reset collector state."""
        self.all_requests.clear()
        self.latencies.clear()
        self.load_samples.clear()
        self.failure_samples.clear()
        self.cascade_detected = False
        self.cascade_start_time = None
        self.overload_start_time = None
        self.failure_end_time = None
        self.recovery_detected_time = None
