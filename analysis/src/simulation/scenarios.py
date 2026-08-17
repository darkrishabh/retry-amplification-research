"""Failure scenarios for simulation experiments."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.models.service import Service


class ScenarioType(Enum):
    """Types of failure scenarios."""
    S1_SINGLE_SERVICE = "S1: Single Service Failure"
    S2_CASCADING_SLOWDOWN = "S2: Cascading Slowdown"
    S3_CORRELATED_FAILURES = "S3: Correlated Failures"
    CUSTOM = "Custom Scenario"


@dataclass
class FailureScenario:
    """
    Defines a failure scenario for simulation.
    
    Scenarios inject failures into the system to test retry behavior.
    
    Attributes:
        name: Human-readable scenario name
        scenario_type: Type of scenario
        start_time: When failures begin (seconds)
        duration: How long failures last (seconds)
        failure_probability: Base failure probability during scenario
        affected_tiers: List of tier indices affected (0-indexed)
        description: Detailed description of the scenario
    """
    
    name: str
    scenario_type: ScenarioType
    start_time: float = 10.0  # Let system stabilize first
    duration: float = 30.0
    failure_probability: float = 0.5
    affected_tiers: list[int] = None
    description: str = ""
    
    # Optional: custom failure injector function
    # Signature: (current_time: float) -> failure_probability: float
    custom_injector: Optional[Callable[[float], float]] = None
    
    def __post_init__(self):
        if self.affected_tiers is None:
            self.affected_tiers = [2]  # Default: middle tier
    
    def get_failure_probability(self, current_time: float, tier_index: int) -> float:
        """
        Get failure probability for a tier at a given time.
        
        Args:
            current_time: Current simulation time
            tier_index: Index of the tier (0 = entry, higher = deeper)
            
        Returns:
            Failure probability (0.0 to 1.0)
        """
        # Check if we're in the failure window
        if current_time < self.start_time or current_time > self.start_time + self.duration:
            return 0.0
        
        # Check if this tier is affected
        if tier_index not in self.affected_tiers:
            return 0.0
        
        # Use custom injector if provided
        if self.custom_injector:
            return self.custom_injector(current_time)
        
        return self.failure_probability
    
    def create_injector(self, tier_index: int) -> Callable[[float], float]:
        """Create a failure injector function for a specific tier."""
        def injector(current_time: float) -> float:
            return self.get_failure_probability(current_time, tier_index)
        return injector
    
    @classmethod
    def s1_single_service_failure(
        cls,
        failure_probability: float = 0.5,
        affected_tier: int = 2,
        start_time: float = 10.0,
        duration: float = 30.0,
    ) -> "FailureScenario":
        """
        Scenario S1: Single Service Failure
        
        50% of requests fail at a single tier (tier 3 by default).
        This simulates a partial outage of one service.
        """
        return cls(
            name="S1: Single Service Failure",
            scenario_type=ScenarioType.S1_SINGLE_SERVICE,
            start_time=start_time,
            duration=duration,
            failure_probability=failure_probability,
            affected_tiers=[affected_tier],
            description=f"50% failure rate at tier {affected_tier + 1}",
        )
    
    @classmethod
    def s2_cascading_slowdown(
        cls,
        start_time: float = 10.0,
        duration: float = 30.0,
    ) -> "FailureScenario":
        """
        Scenario S2: Cascading Slowdown
        
        Latency increase propagates from the deepest tier.
        Failures increase over time as queues build up.
        """
        def cascading_injector(current_time: float) -> float:
            # Failure probability increases over time
            time_in_scenario = current_time - start_time
            if time_in_scenario < 0:
                return 0.0
            # Ramp up from 0.1 to 0.7 over the duration
            progress = min(time_in_scenario / duration, 1.0)
            return 0.1 + 0.6 * progress
        
        return cls(
            name="S2: Cascading Slowdown",
            scenario_type=ScenarioType.S2_CASCADING_SLOWDOWN,
            start_time=start_time,
            duration=duration,
            failure_probability=0.3,  # Base rate
            affected_tiers=[3, 4],  # Deeper tiers
            description="Progressive failure increase in deeper tiers",
            custom_injector=cascading_injector,
        )
    
    @classmethod
    def s3_correlated_failures(
        cls,
        failure_probability: float = 0.6,
        start_time: float = 10.0,
        duration: float = 30.0,
    ) -> "FailureScenario":
        """
        Scenario S3: Correlated Failures
        
        Network partition affects multiple tiers simultaneously.
        This is the worst-case scenario for retry amplification.
        """
        return cls(
            name="S3: Correlated Failures",
            scenario_type=ScenarioType.S3_CORRELATED_FAILURES,
            start_time=start_time,
            duration=duration,
            failure_probability=failure_probability,
            affected_tiers=[2, 3, 4],  # Multiple tiers
            description="Correlated failures across tiers 3-5 (network partition)",
        )
    
    def apply_to_topology(self, services: dict[str, Service]) -> None:
        """
        Apply this failure scenario to a topology's services.
        
        Sets up failure injectors on affected services.
        """
        tier_names = sorted(services.keys())
        
        for tier_index, name in enumerate(tier_names):
            if tier_index in self.affected_tiers:
                services[name].failure_injector = self.create_injector(tier_index)
            else:
                services[name].failure_injector = None
    
    def __repr__(self) -> str:
        return f"FailureScenario({self.name}, tiers={self.affected_tiers}, p={self.failure_probability})"
