# Why Your Retry Logic Is Making Outages Worse

**The counterintuitive truth about retry policies in distributed systems**

---

You've probably added retry logic to your code thinking it would make your system more resilient. After all, transient failures happen—a network blip, a momentary overload, a deployment in progress. Retrying failed requests seems like the obvious solution.

But here's what I discovered after analyzing 200 open-source microservice projects and running thousands of simulations: **your retry logic might be making things worse, not better.**

In fact, under certain failure conditions, services with standard retry policies achieved **25% lower success rates** than services with no retry logic at all.

Let me explain why, and what you can do about it.

---

## The Retry Amplification Problem

Consider a simple three-tier architecture: your API gateway calls an auth service, which calls a user database.

```
User → API Gateway → Auth Service → Database
```

Now imagine the database starts failing 50% of requests due to resource exhaustion. Here's what happens if each service has a standard retry policy of 3 retries:

1. **Database** receives 100 requests, 50 fail
2. **Auth Service** retries those 50 failures → Database now receives 150 requests
3. Some of those retries fail too → More retries → Even more load
4. **API Gateway** sees Auth Service failures → Retries → Cascade multiplies

The math gets ugly fast. In a 5-tier system with 50% failure rates and 3 retries per tier, the theoretical load amplification can reach **6.6×** the normal traffic.

I call this phenomenon **Retry Amplification**—and it can transform a minor degradation into a complete system collapse.

### The Math Behind Retry Amplification

Let me walk you through the actual formula. For a single service with failure probability `p` and maximum `n` retries, the expected number of requests per original request is:

```
RAF = 1 + p + p² + p³ + ... + pⁿ = (1 - p^(n+1)) / (1 - p)
```

For p = 0.5 (50% failure rate) and n = 3 retries:
```
RAF = (1 - 0.5⁴) / (1 - 0.5) = 0.9375 / 0.5 = 1.875
```

So a single tier nearly doubles the load. But here's where it gets scary: **in multi-tier systems, this compounds exponentially**.

For a chain of `d` services, each with the same failure rate and retry policy:
```
RAF_total = RAF^d = 1.875³ ≈ 6.6× for 3 tiers
```

This isn't just theoretical. I've seen production incidents where a single slow database query triggered a retry cascade that generated 10× normal traffic, turning a minor latency spike into a complete outage.

### A Real-World Scenario

Let me paint a more concrete picture. You're running an e-commerce platform during a flash sale:

**Normal state:**
- 1,000 requests/second hitting your API
- Each request flows through 5 services
- Everything responds in <100ms

**Trigger event:**
- Your inventory service gets slow (database connection pool exhausted)
- Response times jump from 50ms to 2 seconds
- Clients start timing out

**The cascade begins:**
1. Your product catalog service sees timeouts → retries 3× → inventory now getting 3,000 req/s instead of 1,000
2. The inventory service, already struggling, fails even more requests
3. Catalog service sees more failures → more retries → inventory at 5,000 req/s
4. Upstream services see catalog failing → they retry → catalog at 3,000 req/s
5. Your API gateway sees everything failing → it retries → multiply everything again

Within 30 seconds, you've gone from "inventory is a bit slow" to "entire platform is down" and your services are drowning in retry traffic that has zero chance of succeeding.

**The cruel irony:** the retry logic you added "for resilience" is now the primary cause of your outage.

---

## What I Found in Real Codebases

I analyzed 200 open-source microservice projects on GitHub to see how developers actually implement retries. The results were concerning:

### Only 11.5% have explicit retry logic

That's it. Nearly 9 out of 10 projects had no visible retry handling in their HTTP clients, RPC calls, or database connections.

But here's the catch: many frameworks have retry logic baked in by default. Your code might be retrying without you realizing it.

### Among projects with retry logic:

Two different denominators are at work here, so I'll label them. *Per project*
counts a project once if any of its configurations shows the pattern (23
projects). *Per configuration* is a share of the 113 distinct production
configurations those projects contain, after excluding documentation, examples
and test code and collapsing near-duplicate detections.

| Configuration | Per project | Per configuration |
|--------------|------------|------------|
| No backoff (immediate retry) | 60.9% (14/23) | 31.0% (35/113) |
| Missing jitter | 95.7% (22/23) | 99.1% (112/113) |
| More than 5 retries | 30.4% (7/23) | 43.8% (32/73) |
| Cross-service coordination | 0% (0/23) | 0% |

Two caveats on those numbers. Retry counts are tabulated only where the code
states one, which is 73 of the 113 — hence the different denominator on that
row. And the 113 are drawn unevenly: one project supplies 23 of them and the top
three supply 44%, so the per-configuration column describes what I found rather
than an independent sample.

Jitter is the one worth staring at. Across all 113 production configurations,
after opening every candidate by hand, **exactly one** randomizes its delay.

**Zero projects** implemented any form of coordinated retry strategy across service boundaries. Every service was making independent retry decisions, oblivious to what was happening upstream or downstream.

---

## The Simulation That Changed My Thinking

I built a discrete-event simulator to test different retry strategies under realistic failure scenarios. I ran 100 trials for each configuration and measured success rates.

The results surprised me:

### Success Rates Under Correlated Failures

| Strategy | Success Rate |
|----------|-------------|
| No Retry | 55.4% |
| Standard Retry (3 retries, exponential backoff, jitter) | **41.5%** |
| Circuit Breaker | 55.3% |
| Adaptive Retry Budgeting | 54.9% |

**Standard Retry performed 25% worse than doing nothing.**

Let that sink in. The "best practice" of adding retries with exponential backoff actually made the system less reliable under stress.

---

## Why Retries Make Things Worse

When I dug into the data, three factors explained the counterintuitive result:

### 1. Queue Competition

Every service has finite capacity—whether that's a thread pool, connection pool, or request queue. When your service is already at capacity, retry traffic doesn't magically create more resources. Instead, retries compete with fresh requests for the same limited slots.

Here's the problem: **a retry is less likely to succeed than a fresh request**.

Why? If the original request failed due to overload, the retry is arriving at a system that's even more overloaded (because of all the other retries). Meanwhile, fresh requests might have been for different resources or different code paths that weren't affected by the original problem.

When you prioritize retries, you're essentially saying "keep trying this thing that already failed" while rejecting "new things that might work." It's like a restaurant that's full continuing to seat parties that already waited an hour, while turning away new customers who might have eaten quickly and left.

### 2. Wasted Capacity

Let's do some quick math on retry success probability.

If your failure rate is 50%, what are the odds of success on:
- 1st attempt: 50%
- 2nd attempt (after 1st failed): 50% (assuming independent failures)
- After 3 retries: 1 - 0.5⁴ = 93.75% cumulative success

That sounds great! But here's what we're not accounting for: **failure rates aren't independent during overload**.

When a service is failing because it's overwhelmed, each retry makes the overload worse. The failure rate isn't a fixed 50%—it's climbing to 60%, 70%, 80% as retry traffic piles up. By the time your third retry arrives, the service might be failing 90% of requests.

My simulations showed that under correlated failures, retry attempts had a success rate of only 15-20%—far below the 50% you'd expect from independent failures. You're spending 4× the resources (original + 3 retries) for diminishing returns.

### 3. Cascading Load

This is the most insidious factor. In a multi-tier system, retries at one level trigger retries at other levels.

Consider what happens when a request fails at Tier 3 in a 5-tier system:

```
Tier 1 (API Gateway)
  └── Tier 2 (Auth)
        └── Tier 3 (Catalog) ← Original failure here
              └── Tier 4 (Inventory)
                    └── Tier 5 (Database)
```

1. Tier 3 fails, Tier 2 retries (up to 3×)
2. Each Tier 2 retry means a new request to Tier 3
3. If those fail, Tier 1 retries Tier 2 (up to 3×)
4. Each Tier 1 retry spawns up to 3 Tier 2 retries, each spawning up to 3 Tier 3 requests

For a single user request, we could generate:
```
1 (original) + 3 (T1 retries) × 3 (T2 retries) × 3 (T3 retries) = 40 downstream requests
```

Now multiply that by 1,000 users making requests, and you see why a small hiccup becomes a tsunami.

### 4. The Thundering Herd (Bonus Factor)

There's a fourth factor I didn't include in the simulation but see constantly in production: **synchronized retries**.

When a service goes down and comes back up, what happens? All the clients that were retrying suddenly succeed—and then immediately send their next requests. You get a massive spike of traffic right when the service is trying to recover.

Without jitter (randomization in retry timing), retries from different clients synchronize:

```
Time 0.0s: Service fails, 1000 clients start retry timers
Time 1.0s: 1000 clients retry simultaneously → Service crashes again
Time 2.0s: 1000 clients retry simultaneously → Service crashes again
Time 4.0s: 1000 clients retry simultaneously → Service crashes again
```

This is why jitter is so important—and why 95% of the projects I analyzed are vulnerable to thundering herd problems.

---

## The Anti-Patterns I Found

Based on my analysis, here are the five retry anti-patterns to avoid:

### 1. No Backoff (60.9% of projects)

```python
# Bad: Immediate retry hammers the failing service
for attempt in range(3):
    try:
        return make_request()
    except Exception:
        continue  # Retry immediately
```

**Fix:** Always use exponential backoff. Start with 100ms, then 200ms, then 400ms.

### 2. Missing Jitter (95% of projects)

```python
# Bad: All clients retry at exactly the same time
delay = base_delay * (2 ** attempt)
```

**Fix:** Add randomization to prevent synchronized retry storms.

```python
# Good: Jitter spreads retries over time
delay = base_delay * (2 ** attempt) * (0.5 + random.random())
```

### 3. Aggressive Retry Counts

Using 5, 10, or even unlimited retries might seem thorough, but it just prolongs the pain. Industry guidance (AWS, Google) recommends **3 retries maximum**.

### 4. Static Configuration

Every project I analyzed used fixed retry parameters. None adapted based on current system conditions. When failure rates spike, you should be retrying *less*, not the same amount.

### 5. No Cross-Service Awareness

Your API gateway doesn't know that your database is drowning in retry traffic from three intermediate services. Without coordination, each tier independently decides to retry, creating multiplicative amplification.

---

## A Better Approach: Adaptive Retry Budgeting

Based on my research, I developed an algorithm called **Adaptive Retry Budgeting (ARB)** that addresses these issues. But before I show you the code, let me explain the thinking behind it.

### Why Traditional Retry Logic Fails

Traditional retry policies ask: **"Should I retry this failed request?"**

The decision is made locally, based only on:
- How many times have I already retried?
- What kind of error was it?
- How long should I wait before retrying?

This is the wrong question. It ignores crucial context:
- Is the downstream service overwhelmed?
- Are hundreds of other clients also retrying right now?
- Is my retry traffic making the problem worse?

### The Right Question

ARB asks a different question: **"How much retry traffic can the system afford right now?"**

Instead of "retry up to N times," think "allow retry traffic up to X% of normal load." This reframes retry capacity as a **shared system resource** rather than an individual decision.

### The Core Idea

```python
class AdaptiveRetryBudget:
    def __init__(self, budget=0.2):  # Allow 20% retry traffic
        self.budget = budget
        self.failure_rate = 0.0
    
    def should_retry(self, downstream_overloaded=False):
        # Respect backpressure signals
        if downstream_overloaded:
            return False
        
        # Probabilistic retry based on remaining budget
        if self.budget <= 0:
            return False
            
        # Less likely to retry when failure rate is high
        probability = min(self.budget, 1 - self.failure_rate)
        return random.random() < probability
    
    def adjust_budget(self):
        # Reduce budget when things are bad
        if self.failure_rate > 0.3:
            self.budget *= 0.5
        # Slowly recover when things improve
        elif self.failure_rate < 0.05:
            self.budget = min(0.2, self.budget + 0.1)
```

### How It Works: A Walkthrough

Let me trace through what happens during a failure scenario:

**Normal operation (failure rate ~1%):**
- Budget stays at 20%
- The rare failed request gets retried (probability check passes)
- Retries mostly succeed because the system is healthy
- Everyone's happy

**Failure begins (failure rate jumps to 30%):**
- `failure_rate > 0.3` → budget cuts in half to 10%
- Fewer retries are attempted
- Each retry has lower probability: `min(0.1, 1 - 0.3) = 0.1`
- Only 10% of failures get retried

**Failure worsens (failure rate at 60%):**
- Budget cuts in half again → 5%
- Retry probability: `min(0.05, 1 - 0.6) = 0.05`
- Only 5% of failures get retried
- System prioritizes new requests over retries

**Downstream signals OVERLOADED:**
- All retries stop immediately
- Zero retry traffic added to struggling service
- Maximum protection for downstream

**Recovery (failure rate drops to 2%):**
- Budget slowly increases: 5% → 15% → 20%
- Gradual ramp-up prevents thundering herd
- System returns to normal operation

### Why This Works

The key insight is that ARB implements **negative feedback**:
- High failure rate → fewer retries → less load → failure rate drops
- Low failure rate → more retries allowed → transient failures recovered

Traditional retry logic implements **positive feedback**:
- High failure rate → lots of retries → more load → higher failure rate → catastrophe

### Key Principles

1. **Budget-based:** Treat retry capacity as a limited resource that gets consumed
2. **Adaptive:** Reduce retries when failure rates increase (the opposite of what you'd naively expect)
3. **Backpressure-aware:** Stop retrying immediately when downstream signals overload
4. **Probabilistic:** Not all failures get retried—this prevents the "everyone retries everything" problem
5. **Gradual recovery:** Slow budget increase prevents thundering herd on recovery

### Simulation Results

In my simulations, ARB achieved:
- **54.9% success rate** under correlated failures (vs 41.5% for standard retry)
- **1.01× RAF** (essentially no amplification, vs 1.34× for standard retry)
- Success rates within 1% of "no retry" baseline

ARB proves you can have resilience benefits without amplification risks—you just need to think about retries as a system-wide resource, not a local decision.

---

## Practical Recommendations

Here's what you should do today, ranked by impact and effort:

### 1. Audit Your Retry Configurations (Do This First)

You might have more retry logic than you realize. Search your codebase:

```bash
# Python
rg -i "retry|backoff|tenacity|urllib3\.retry" --type py

# Go
rg -i "RetryMax|backoff|ExponentialBackoff" --type go

# Java
rg -i "@Retryable|RetryTemplate|Resilience4j" --type java

# JavaScript/TypeScript
rg -i "axios-retry|retry|backoff" --type js --type ts
```

**Don't forget hidden retries!** Many libraries have retry behavior enabled by default:

| Library | Default Behavior |
|---------|------------------|
| AWS SDK | 3 retries with exponential backoff |
| gRPC | Configurable, often enabled |
| Kubernetes client | Built-in retry for transient errors |
| Most database drivers | Connection retry on failure |
| axios (with axios-retry) | Must be explicitly configured |
| requests (Python) | No retry by default |

Create a spreadsheet documenting every retry configuration in your system. You'll probably be surprised by what you find.

### 2. Add Jitter Everywhere (Highest Impact, Lowest Effort)

This is the single highest-impact change you can make. If you have exponential backoff without jitter, add it now:

```python
import random

def backoff_with_jitter(attempt, base_delay=0.1):
    """
    Exponential backoff with full jitter.
    
    Attempt 0: 0-100ms
    Attempt 1: 0-200ms  
    Attempt 2: 0-400ms
    Attempt 3: 0-800ms
    """
    max_delay = base_delay * (2 ** attempt)
    return random.uniform(0, max_delay)
```

There are three common jitter strategies:

```python
# Full jitter (recommended): delay = random(0, calculated_delay)
def full_jitter(attempt, base=0.1):
    return random.uniform(0, base * (2 ** attempt))

# Equal jitter: delay = calculated_delay/2 + random(0, calculated_delay/2)
def equal_jitter(attempt, base=0.1):
    delay = base * (2 ** attempt)
    return delay / 2 + random.uniform(0, delay / 2)

# Decorrelated jitter: delay = random(base, previous_delay * 3)
def decorrelated_jitter(attempt, base=0.1, previous=0.1):
    return random.uniform(base, previous * 3)
```

AWS recommends **full jitter** for most cases—it provides the best spread of retry times.

### 3. Limit Retry Counts (Quick Win)

If you're using more than 3 retries, ask yourself why. Here's a decision framework:

| Retry Count | When to Use |
|-------------|-------------|
| 0 | Real-time operations where stale data is worse than no data |
| 1 | Operations where transient failures are rare |
| 2-3 | Most API calls, database operations |
| 4+ | Almost never—indicates a design problem |

If you feel you need 5+ retries, you probably have one of these issues:
- Unreliable downstream service (fix the service, don't band-aid with retries)
- Wrong timeout values (increase timeout instead of retry count)
- Non-transient failures being retried (improve error classification)

### 4. Implement Circuit Breakers (Medium Effort, High Impact)

Circuit breakers are complementary to retry logic. While retries help with transient failures, circuit breakers protect against sustained failures:

```python
from circuitbreaker import circuit

@circuit(
    failure_threshold=5,      # Open after 5 failures
    recovery_timeout=30,      # Try again after 30 seconds
    expected_exception=Exception
)
def call_downstream_service():
    return requests.get("http://downstream/api", timeout=5)
```

**Circuit breaker states:**
- **Closed:** Normal operation, requests pass through
- **Open:** Too many failures, requests fail immediately (no downstream call)
- **Half-Open:** After timeout, allow one request to test if service recovered

The key insight: when the circuit is open, you're **not adding retry traffic** to an already-failing service. This is exactly what you want.

**Popular libraries:**
- Python: `circuitbreaker`, `pybreaker`, `tenacity`
- Java: `Resilience4j`, `Hystrix` (deprecated but still used)
- Go: `sony/gobreaker`, `afex/hystrix-go`
- JavaScript: `opossum`, `cockatiel`

### 5. Add Backpressure Signals (Medium Effort)

Have your services communicate when they're struggling. This lets upstream services make informed decisions:

```python
from flask import Flask, request, make_response
import psutil

app = Flask(__name__)

@app.after_request
def add_backpressure_header(response):
    # Calculate load based on CPU and queue depth
    cpu_percent = psutil.cpu_percent()
    queue_depth = get_request_queue_depth()  # Your implementation
    
    # Normalize to 0-1 scale
    load = max(cpu_percent / 100, queue_depth / MAX_QUEUE)
    
    if load > 0.7:
        response.headers['X-Backpressure'] = f'{load:.2f}'
        
        # If critically overloaded, suggest retry-after
        if load > 0.9:
            response.headers['Retry-After'] = '30'
    
    return response
```

Upstream services can then respect this signal:

```python
def call_with_backpressure_awareness(url):
    response = requests.get(url)
    
    backpressure = float(response.headers.get('X-Backpressure', 0))
    
    if backpressure > 0.8:
        # Don't retry, downstream is struggling
        raise BackpressureException("Downstream overloaded")
    
    return response
```

### 6. Monitor Retry Metrics (Essential for Production)

You can't improve what you don't measure. Track these metrics:

```python
from prometheus_client import Counter, Histogram, Gauge

# Count of retry attempts
retry_attempts = Counter(
    'http_client_retry_attempts_total',
    'Total retry attempts',
    ['service', 'endpoint', 'attempt_number']
)

# Retry success rate
retry_success = Counter(
    'http_client_retry_success_total', 
    'Successful retries',
    ['service', 'endpoint']
)

retry_failure = Counter(
    'http_client_retry_failure_total',
    'Failed retries (exhausted all attempts)',
    ['service', 'endpoint']
)

# Load amplification factor
request_amplification = Gauge(
    'http_client_request_amplification',
    'Ratio of actual requests to original requests',
    ['service']
)
```

**Key metrics to alert on:**

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Retry rate | <5% of traffic | 5-15% | >15% |
| Retry success rate | >80% | 50-80% | <50% |
| Load amplification | <1.1× | 1.1-1.5× | >1.5× |

**If your retry success rate drops below 50%, your retries are hurting more than helping.** Consider temporarily disabling retries or dramatically reducing retry counts.

---

## How I Tested This

You might be wondering: "How do you actually measure retry amplification? How do you know standard retry is worse?"

I built a discrete-event simulator that models a 5-tier microservice architecture. Here's what it simulates:

```
Load Generator → API → Auth → Catalog → Inventory → Database
                 ↓      ↓       ↓          ↓           ↓
              Queue   Queue   Queue      Queue       Queue
              1000    1000    1000       1000        1000
              RPS     RPS     RPS        RPS         RPS
```

Each service has:
- 1,000 requests/second capacity
- 500 requests/second base load (50% utilization)
- Configurable retry policy
- Queue with load shedding when full

I tested three failure scenarios:

1. **S1 - Single Service Failure:** 50% of requests fail at the Catalog tier
2. **S2 - Cascading Slowdown:** Latency increases progressively from Database up
3. **S3 - Correlated Failures:** Network partition affects tiers 3-5 simultaneously

For each scenario, I ran **100 trials** with each retry strategy and measured:
- Success rate (% of original requests that eventually succeed)
- Retry Amplification Factor (actual requests / expected requests)
- Recovery time (how long until the system stabilizes after failure ends)

### The Results Visualized

```
Success Rate Under Correlated Failures (S3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No Retry      ████████████████████████████████████████████████░░  55.4%
Std Retry     █████████████████████████████████░░░░░░░░░░░░░░░░░  41.5%  ← 25% WORSE
Circuit Brk   ████████████████████████████████████████████████░░  55.3%
ARB           ███████████████████████████████████████████████░░░  54.9%
```

```
Retry Amplification Factor (S3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No Retry      █                    1.00×
Std Retry     █████████████        1.34×  ← 34% more traffic
Circuit Brk   █                    1.00×
ARB           █                    1.01×
```

The numbers tell a clear story:
- Standard Retry generates 34% more traffic AND achieves 25% lower success
- Circuit Breaker and ARB avoid amplification while matching baseline success rates

### Why Didn't Observed RAF Match Theoretical?

You might notice that I predicted RAF up to 6.6× but only observed 1.34×. Three factors explain this:

1. **Finite queues:** My simulation has bounded queues with load shedding. Real systems do too—unbounded queues just mean unbounded memory usage and eventual OOM.

2. **Backoff delays:** Exponential backoff spreads retries over time. The theoretical formula assumes instantaneous retries.

3. **Simulation duration:** Reaching theoretical steady-state RAF requires long observation windows. My simulations ran for 55 seconds total.

The relative comparison is what matters: Standard Retry was significantly worse than alternatives, even if absolute numbers differed from theory.

## The Bigger Picture

The core insight from this research is that **retries must be designed as a system property, not a local optimization**.

When each service independently implements retry policies, the emergent behavior can be catastrophic. A retry that makes sense for one service in isolation might contribute to system-wide collapse when multiplied across tiers.

### The Tragedy of the Commons

Retry logic suffers from a classic tragedy of the commons problem:

- **Individual incentive:** Each service wants to retry for maximum reliability
- **Collective outcome:** Everyone retrying creates catastrophic load

No single service is "wrong" to retry—the problem is that everyone is making the same individually-rational decision, leading to a collectively-irrational outcome.

This is why coordination matters. Whether it's retry budgets in your service mesh, backpressure signals between services, or a centralized rate limiter, you need some mechanism that considers the system-wide impact of retry decisions.

### When Retries Actually Help

I don't want to leave you thinking retries are always bad. They're valuable for:

1. **Genuinely transient failures:** Network blip, GC pause, momentary resource contention
2. **Low-volume operations:** Batch jobs, cron tasks, admin operations
3. **Idempotent operations:** Where retrying has no side effects
4. **Circuit-breaker-protected paths:** Where sustained failures get cut off quickly

The key is understanding the failure mode:

| Failure Type | Should Retry? | Why |
|--------------|---------------|-----|
| Network timeout (one-off) | Yes | Transient, might succeed |
| 503 Service Unavailable | Maybe | Could be transient or sustained |
| 429 Too Many Requests | Respect Retry-After | Server is explicitly throttling |
| 500 Internal Server Error | Maybe | Depends on root cause |
| Connection refused | Usually no | Service is down, retry won't help |
| DNS resolution failure | No | Indicates serious infrastructure issue |

### The Mindset Shift

The next time you're tempted to add retry logic "for resilience," ask yourself:
- What happens if every service in the call chain does this?
- How will this behave when the downstream service is already overloaded?
- Am I making the system more resilient, or just delaying failure while making it worse?
- Is there a way to communicate with downstream about whether retries are helpful?

Sometimes the most resilient thing you can do is fail fast and let the system recover.

## Conclusion

Retry policies are one of those things that seem obviously good but have subtle failure modes that only manifest at scale, under pressure. The 25% performance degradation I measured isn't a bug in any individual service—it's an emergent property of uncoordinated retry behavior.

**Key takeaways:**

1. **Retries can make things worse**, not just fail to help
2. **95% of projects lack jitter**, making them vulnerable to thundering herds
3. **0% coordinate across services**, leading to multiplicative amplification
4. **Adaptive approaches work**: Circuit breakers and ARB avoid amplification while preserving resilience benefits

The solution isn't to remove all retries—it's to think about them as a system-wide resource that needs coordination and limits. Whether you implement ARB, use circuit breakers, add retry budgets in your service mesh, or simply add jitter and reduce retry counts, any step toward coordinated retry behavior is a step toward a more resilient system.

Your future self, debugging a 3 AM outage, will thank you.

---

## Resources

- **Simulation code and data:** [GitHub repository - coming soon]
- **AWS: Exponential Backoff and Jitter:** [aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)
- **Google Cloud: Retry Best Practices:** [cloud.google.com/architecture/best-practices-for-retry](https://cloud.google.com/architecture/best-practices-for-retry)
- **Envoy Retry Budgets:** [envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http_routing](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http_routing#retry-semantics)

---

*Rishabh Mehan is a software engineer researching distributed systems reliability. This article summarizes findings from "Retry Amplification in Distributed Systems: A Systematic Analysis of Retry Policies and Their Role in Cascading Failures."*
