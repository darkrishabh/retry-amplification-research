"""Service model for the simulation."""

from dataclasses import dataclass, field
from typing import Optional, Callable, TYPE_CHECKING
from collections import deque
import random

from .request import Request, RequestStatus

if TYPE_CHECKING:
    import simpy


@dataclass
class ServiceMetrics:
    """Metrics collected for a service during simulation."""
    
    # Request counts
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    retry_requests: int = 0
    
    # Timing
    total_latency: float = 0.0
    total_queue_time: float = 0.0
    total_processing_time: float = 0.0
    
    # Load tracking (time series)
    load_samples: list = field(default_factory=list)  # (time, load) tuples
    queue_depth_samples: list = field(default_factory=list)
    
    # Peak values
    peak_load: float = 0.0
    peak_queue_depth: int = 0
    
    # Cascade detection
    overload_start_time: Optional[float] = None
    overload_duration: float = 0.0
    was_overloaded: bool = False
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate."""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests
    
    @property
    def avg_latency(self) -> float:
        """Average latency per request."""
        completed = self.successful_requests + self.failed_requests
        if completed == 0:
            return 0.0
        return self.total_latency / completed
    
    @property
    def retry_rate(self) -> float:
        """Proportion of requests that are retries."""
        if self.total_requests == 0:
            return 0.0
        return self.retry_requests / self.total_requests


class Service:
    """
    Represents a service in the distributed system.
    
    Models:
    - Request queue with capacity limits
    - Processing with configurable concurrency
    - Failure injection
    - Downstream dependencies
    - Backpressure signaling
    """
    
    def __init__(
        self,
        env: "simpy.Environment",
        name: str,
        capacity: float = 1000.0,  # requests per second
        base_processing_time: float = 0.01,  # seconds (10ms)
        max_queue_size: int = 1000,
        failure_probability: float = 0.0,
        downstream_services: Optional[list["Service"]] = None,
    ):
        self.env = env
        self.name = name
        self.capacity = capacity
        self.base_processing_time = base_processing_time
        self.max_queue_size = max_queue_size
        self.base_failure_probability = failure_probability
        self.current_failure_probability = failure_probability
        self.downstream_services = downstream_services or []
        
        # SimPy resources
        # Use capacity as concurrent workers (capacity / 100 gives reasonable concurrency)
        import simpy
        self.workers = simpy.Resource(env, capacity=max(1, int(capacity / 100)))
        
        # Queue
        self.queue: deque[Request] = deque()
        
        # State
        self.is_overloaded = False
        self.backpressure_signal = 0.0  # 0.0 = healthy, 1.0 = fully overloaded
        
        # Metrics
        self.metrics = ServiceMetrics()
        
        # Load tracking
        self._request_times: deque[float] = deque()
        self._load_window = 1.0  # 1 second window for load calculation
        
        # Failure injection callback (can be set externally)
        self.failure_injector: Optional[Callable[[float], float]] = None
    
    @property
    def current_load(self) -> float:
        """Calculate current request rate (requests per second)."""
        now = self.env.now
        # Remove old entries
        while self._request_times and self._request_times[0] < now - self._load_window:
            self._request_times.popleft()
        return len(self._request_times) / self._load_window
    
    @property
    def queue_depth(self) -> int:
        """Current queue depth."""
        return len(self.queue)
    
    @property
    def utilization(self) -> float:
        """Current utilization (0.0 to 1.0+)."""
        return self.current_load / self.capacity
    
    def update_backpressure(self) -> None:
        """Update backpressure signal based on current state."""
        queue_pressure = self.queue_depth / self.max_queue_size if self.max_queue_size > 0 else 0
        load_pressure = self.utilization
        
        self.backpressure_signal = max(queue_pressure, load_pressure)
        # Lower threshold to detect overload more readily
        self.is_overloaded = self.backpressure_signal > 0.7 or self.current_failure_probability > 0.3
        
        # Track overload for cascade detection
        if self.is_overloaded:
            if self.metrics.overload_start_time is None:
                self.metrics.overload_start_time = self.env.now
            self.metrics.was_overloaded = True
        else:
            if self.metrics.overload_start_time is not None:
                self.metrics.overload_duration += self.env.now - self.metrics.overload_start_time
                self.metrics.overload_start_time = None
    
    def should_fail(self) -> bool:
        """Determine if request should fail based on failure probability."""
        # Apply failure injector if set
        if self.failure_injector:
            self.current_failure_probability = self.failure_injector(self.env.now)
        
        # Higher failure rate under overload
        effective_failure_prob = self.current_failure_probability
        if self.utilization > 1.0:
            # Increase failure probability when overloaded
            overload_factor = min(self.utilization - 1.0, 1.0)
            effective_failure_prob = min(1.0, effective_failure_prob + overload_factor * 0.5)
        
        return random.random() < effective_failure_prob
    
    def accept_request(self, request: Request) -> bool:
        """
        Try to accept a request into the queue.
        Returns False if request is rejected (load shedding).
        """
        self._request_times.append(self.env.now)
        self.metrics.total_requests += 1
        
        if request.is_retry:
            self.metrics.retry_requests += 1
        
        # Update metrics
        current_load = self.current_load
        if current_load > self.metrics.peak_load:
            self.metrics.peak_load = current_load
        
        self.metrics.load_samples.append((self.env.now, current_load))
        self.metrics.queue_depth_samples.append((self.env.now, self.queue_depth))
        
        if self.queue_depth > self.metrics.peak_queue_depth:
            self.metrics.peak_queue_depth = self.queue_depth
        
        # Load shedding
        if self.queue_depth >= self.max_queue_size:
            request.status = RequestStatus.REJECTED
            self.metrics.rejected_requests += 1
            return False
        
        self.queue.append(request)
        self.update_backpressure()
        return True
    
    def process_request(self, request: Request) -> "simpy.events.Event":
        """Process a request through this service."""
        request.start_time = self.env.now
        request.status = RequestStatus.IN_PROGRESS
        
        # Wait for worker
        with self.workers.request() as worker_req:
            yield worker_req
            
            queue_wait = self.env.now - request.start_time
            request.queue_time = queue_wait
            self.metrics.total_queue_time += queue_wait
            
            # Simulate processing time with some variance
            processing_time = self.base_processing_time * (0.8 + random.random() * 0.4)
            yield self.env.timeout(processing_time)
            
            request.processing_time = processing_time
            self.metrics.total_processing_time += processing_time
            
            # Check for failure
            if self.should_fail():
                request.status = RequestStatus.FAILED
                request.error_message = "Service failure"
                self.metrics.failed_requests += 1
            else:
                # Process downstream if needed
                if self.downstream_services:
                    downstream_success = yield from self._process_downstream(request)
                    if not downstream_success:
                        request.status = RequestStatus.FAILED
                        request.error_message = "Downstream failure"
                        self.metrics.failed_requests += 1
                    else:
                        request.status = RequestStatus.SUCCESS
                        self.metrics.successful_requests += 1
                else:
                    request.status = RequestStatus.SUCCESS
                    self.metrics.successful_requests += 1
            
            request.end_time = self.env.now
            self.metrics.total_latency += request.total_latency
            
            # Remove from queue
            if request in self.queue:
                self.queue.remove(request)
            
            self.update_backpressure()
    
    def _process_downstream(self, request: Request) -> bool:
        """Process request through downstream services."""
        for downstream in self.downstream_services:
            downstream_req = Request(
                origin_time=request.origin_time,
                source_service=self.name,
                target_service=downstream.name,
            )
            request.downstream_requests.append(downstream_req)
            
            if not downstream.accept_request(downstream_req):
                return False
            
            yield from downstream.process_request(downstream_req)
            
            if downstream_req.status != RequestStatus.SUCCESS:
                return False
            
            request.downstream_latency += downstream_req.total_latency
        
        return True
    
    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self.metrics = ServiceMetrics()
        self._request_times.clear()
    
    def __repr__(self) -> str:
        return f"Service({self.name}, capacity={self.capacity}, load={self.current_load:.1f})"
