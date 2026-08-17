"""Topology model for multi-tier service architectures."""

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import simpy
    from .service import Service


@dataclass
class ServiceConfig:
    """Configuration for a service in the topology."""
    
    name: str
    capacity: float = 1000.0  # requests per second
    base_processing_time: float = 0.01  # 10ms
    max_queue_size: int = 1000
    failure_probability: float = 0.0
    downstream: list[str] = field(default_factory=list)


class Topology:
    """
    Represents a service topology (dependency graph).
    
    Supports:
    - Linear chains (A -> B -> C)
    - Trees (A -> [B, C], B -> [D, E])
    - DAGs (general directed acyclic graphs)
    """
    
    def __init__(self, env: "simpy.Environment"):
        self.env = env
        self.services: dict[str, "Service"] = {}
        self.entry_points: list[str] = []  # Services that receive external traffic
    
    @classmethod
    def create_linear_chain(
        cls,
        env: "simpy.Environment",
        num_tiers: int = 5,
        capacity: float = 1000.0,
        base_processing_time: float = 0.01,
        failure_probability: float = 0.0,
        tier_names: Optional[list[str]] = None,
    ) -> "Topology":
        """
        Create a linear chain topology.
        
        Example: API -> Auth -> Catalog -> Inventory -> Database
        """
        from .service import Service
        
        topology = cls(env)
        
        if tier_names is None:
            tier_names = [f"Tier{i}" for i in range(num_tiers)]
        
        # Create services from bottom up (so we can set downstream)
        services_list: list[Service] = []
        
        for i in range(num_tiers - 1, -1, -1):
            downstream = [services_list[-1]] if services_list else []
            
            service = Service(
                env=env,
                name=tier_names[i],
                capacity=capacity,
                base_processing_time=base_processing_time,
                failure_probability=failure_probability,
                downstream_services=downstream,
            )
            services_list.append(service)
            topology.services[tier_names[i]] = service
        
        # Entry point is the first tier
        topology.entry_points = [tier_names[0]]
        
        return topology
    
    @classmethod
    def create_from_config(
        cls,
        env: "simpy.Environment",
        configs: list[ServiceConfig],
        entry_points: list[str],
    ) -> "Topology":
        """Create topology from a list of service configurations."""
        from .service import Service
        
        topology = cls(env)
        
        # First pass: create all services without downstream
        for config in configs:
            service = Service(
                env=env,
                name=config.name,
                capacity=config.capacity,
                base_processing_time=config.base_processing_time,
                max_queue_size=config.max_queue_size,
                failure_probability=config.failure_probability,
            )
            topology.services[config.name] = service
        
        # Second pass: wire up downstream dependencies
        for config in configs:
            service = topology.services[config.name]
            service.downstream_services = [
                topology.services[name] for name in config.downstream
                if name in topology.services
            ]
        
        topology.entry_points = entry_points
        return topology
    
    def get_entry_service(self) -> Optional["Service"]:
        """Get the primary entry point service."""
        if self.entry_points:
            return self.services.get(self.entry_points[0])
        return None
    
    def get_terminal_services(self) -> list["Service"]:
        """Get services with no downstream dependencies."""
        return [
            s for s in self.services.values()
            if not s.downstream_services
        ]
    
    def reset_all_metrics(self) -> None:
        """Reset metrics for all services."""
        for service in self.services.values():
            service.reset_metrics()
    
    def get_aggregate_metrics(self) -> dict:
        """Get aggregated metrics across all services."""
        total_requests = sum(s.metrics.total_requests for s in self.services.values())
        total_success = sum(s.metrics.successful_requests for s in self.services.values())
        total_failed = sum(s.metrics.failed_requests for s in self.services.values())
        total_rejected = sum(s.metrics.rejected_requests for s in self.services.values())
        
        # Calculate RAF for terminal services
        terminal = self.get_terminal_services()
        if terminal:
            base_load = terminal[0].capacity * 0.5  # Assuming 50% base utilization
            actual_load = sum(s.metrics.peak_load for s in terminal)
            raf = actual_load / base_load if base_load > 0 else 1.0
        else:
            raf = 1.0
        
        # Check for cascade (all services overloaded for extended period)
        cascade_occurred = all(
            s.metrics.was_overloaded and s.metrics.overload_duration > 60
            for s in self.services.values()
        )
        
        return {
            "total_requests": total_requests,
            "successful_requests": total_success,
            "failed_requests": total_failed,
            "rejected_requests": total_rejected,
            "success_rate": total_success / total_requests if total_requests > 0 else 0,
            "raf": raf,
            "cascade_occurred": cascade_occurred,
            "services": {
                name: {
                    "total_requests": s.metrics.total_requests,
                    "success_rate": s.metrics.success_rate,
                    "peak_load": s.metrics.peak_load,
                    "peak_queue": s.metrics.peak_queue_depth,
                    "avg_latency": s.metrics.avg_latency,
                    "overload_duration": s.metrics.overload_duration,
                }
                for name, s in self.services.items()
            }
        }
    
    def __repr__(self) -> str:
        return f"Topology({len(self.services)} services, entry={self.entry_points})"
