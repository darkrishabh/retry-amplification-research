#!/usr/bin/env python3
"""
Main experiment runner for retry amplification research.

Reproduces the experiments from the paper:
- Table 3: RAF under failure scenarios
- Table 4: Anti-pattern impact
- Table 5: Strategy comparison
- Table 6: Recovery time analysis

Usage:
    python experiments/run_simulation.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import pandas as pd

from src.policies import (
    NoRetryPolicy,
    StandardRetryPolicy,
    CircuitBreakerPolicy,
    AdaptiveRetryBudgetingPolicy,
)
from src.policies.standard_retry import AggressiveRetryPolicy, ImmediateRetryPolicy
from src.simulation import SimulationConfig, FailureScenario
from src.simulation.engine import run_experiment, aggregate_results


console = Console()


def run_main_experiments(num_trials: int = 100, seed: int = 42):
    """
    Run the main experiments from the paper.
    
    Returns:
        Dictionary containing all results
    """
    console.print("\n[bold blue]Retry Amplification Research - Experiment Runner[/bold blue]")
    console.print(f"Running {num_trials} trials per configuration\n")
    
    # Configuration matching the paper
    config = SimulationConfig(
        num_tiers=5,
        service_capacity=1000.0,
        base_processing_time=0.005,  # 5ms processing
        max_queue_size=500,
        base_load=500.0,
        warmup_duration=5.0,  # Reduced for faster testing
        scenario_duration=20.0,  # Reduced for faster testing
        cooldown_duration=30.0,  # Reduced for faster testing
        sample_interval=1.0,  # Less frequent sampling
    )
    
    # Create scenarios
    scenarios = {
        "S1": FailureScenario.s1_single_service_failure(
            failure_probability=0.5,
            affected_tier=2,
            start_time=config.warmup_duration,
            duration=config.scenario_duration,
        ),
        "S2": FailureScenario.s2_cascading_slowdown(
            start_time=config.warmup_duration,
            duration=config.scenario_duration,
        ),
        "S3": FailureScenario.s3_correlated_failures(
            failure_probability=0.6,
            start_time=config.warmup_duration,
            duration=config.scenario_duration,
        ),
    }
    
    # Create policies
    policies = {
        "NR": NoRetryPolicy(),
        "SR": StandardRetryPolicy(max_retries=3, jitter=True),
        "CB": CircuitBreakerPolicy(
            failure_threshold=0.5,
            recovery_timeout=30.0,
        ),
        "ARB": AdaptiveRetryBudgetingPolicy(
            alpha=0.1,
            beta=0.5,
            theta_high=0.3,
            theta_low=0.05,
            max_retries=3,
        ),
    }
    
    all_results = {}
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        
        total_experiments = len(policies) * len(scenarios)
        main_task = progress.add_task(
            "[cyan]Running experiments...", 
            total=total_experiments
        )
        
        for policy_name, policy in policies.items():
            all_results[policy_name] = {}
            
            for scenario_name, scenario in scenarios.items():
                progress.update(
                    main_task,
                    description=f"[cyan]{policy_name} + {scenario_name}..."
                )
                
                # Run trials
                results = run_experiment(
                    policy=policy,
                    scenario=scenario,
                    config=config,
                    num_trials=num_trials,
                    seed=seed,
                )
                
                # Aggregate results
                aggregated = aggregate_results(results)
                all_results[policy_name][scenario_name] = aggregated
                
                progress.advance(main_task)
    
    return all_results


def print_table_3(results: dict):
    """Print Table 3: RAF under failure scenarios."""
    console.print("\n[bold]Table 3: Retry Amplification Under Failure Scenarios[/bold]")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Scenario")
    table.add_column("Theoretical RAF")
    table.add_column("Observed RAF (95% CI)")
    
    # Theoretical values from paper
    theoretical = {"S1": 2.88, "S2": 5.12, "S3": 7.94}
    
    # Use Standard Retry results
    sr_results = results.get("SR", {})
    
    for scenario in ["S1", "S2", "S3"]:
        if scenario in sr_results:
            r = sr_results[scenario]
            observed = f"{r['raf_mean']:.1f} (±{r['raf_ci']:.1f})"
        else:
            observed = "N/A"
        
        table.add_row(
            scenario,
            f"{theoretical[scenario]:.2f}",
            observed,
        )
    
    console.print(table)


def print_table_5(results: dict):
    """Print Table 5: Strategy comparison across failure scenarios."""
    console.print("\n[bold]Table 5: Strategy Comparison Across Failure Scenarios[/bold]")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Strategy")
    table.add_column("S1 Cascade %")
    table.add_column("S2 Cascade %")
    table.add_column("S3 Cascade %")
    table.add_column("Avg Success Rate")
    
    for policy_name in ["NR", "SR", "CB", "ARB"]:
        policy_results = results.get(policy_name, {})
        
        s1 = policy_results.get("S1", {})
        s2 = policy_results.get("S2", {})
        s3 = policy_results.get("S3", {})
        
        # Calculate average success rate across scenarios
        success_rates = [
            r.get("success_rate_mean", 0) 
            for r in [s1, s2, s3] 
            if r
        ]
        avg_success = sum(success_rates) / len(success_rates) if success_rates else 0
        
        def format_cascade(r):
            if not r:
                return "N/A"
            prob = r.get("cascade_probability", 0) * 100
            ci = r.get("cascade_ci", 0) * 100
            return f"{prob:.0f}% (±{ci:.0f}%)"
        
        def format_success(rate, ci):
            return f"{rate * 100:.1f}% (±{ci * 100:.1f}%)"
        
        avg_ci = sum(r.get("success_rate_ci", 0) for r in [s1, s2, s3] if r) / 3
        
        table.add_row(
            policy_name,
            format_cascade(s1),
            format_cascade(s2),
            format_cascade(s3),
            format_success(avg_success, avg_ci),
        )
    
    console.print(table)


def print_table_6(results: dict):
    """Print Table 6: Time to recovery after failure injection ends."""
    console.print("\n[bold]Table 6: Time to Recovery After Failure Injection Ends[/bold]")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Strategy")
    table.add_column("S1 Recovery")
    table.add_column("S2 Recovery")
    table.add_column("S3 Recovery")
    
    for policy_name in ["SR", "CB", "ARB"]:
        policy_results = results.get(policy_name, {})
        
        def format_recovery(r):
            if not r:
                return "N/A"
            recovery = r.get("recovery_time_mean")
            if recovery is None:
                return ">120s*"
            return f"{recovery:.1f}s"
        
        table.add_row(
            policy_name,
            format_recovery(policy_results.get("S1")),
            format_recovery(policy_results.get("S2")),
            format_recovery(policy_results.get("S3")),
        )
    
    console.print(table)
    console.print("[dim]*System did not recover within simulation window[/dim]")


def calculate_reduction(results: dict):
    """Calculate the cascade probability reduction of ARB vs SR."""
    sr = results.get("SR", {})
    arb = results.get("ARB", {})
    
    sr_cascades = []
    arb_cascades = []
    
    for scenario in ["S1", "S2", "S3"]:
        if scenario in sr:
            sr_cascades.append(sr[scenario].get("cascade_probability", 0))
        if scenario in arb:
            arb_cascades.append(arb[scenario].get("cascade_probability", 0))
    
    sr_total = sum(sr_cascades)
    arb_total = sum(arb_cascades)
    
    if sr_total > 0:
        reduction = (sr_total - arb_total) / sr_total * 100
        console.print(f"\n[bold green]ARB reduces cascade probability by {reduction:.0f}% vs Standard Retry[/bold green]")


def save_results(results: dict, output_dir: Path):
    """Save results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as JSON
    json_path = output_dir / "experiment_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    # Save as CSV for each scenario
    for scenario in ["S1", "S2", "S3"]:
        rows = []
        for policy_name in ["NR", "SR", "CB", "ARB"]:
            if policy_name in results and scenario in results[policy_name]:
                r = results[policy_name][scenario]
                rows.append({
                    "policy": policy_name,
                    "scenario": scenario,
                    "cascade_probability": r.get("cascade_probability", 0),
                    "raf_mean": r.get("raf_mean", 0),
                    "success_rate_mean": r.get("success_rate_mean", 0),
                    "recovery_time_mean": r.get("recovery_time_mean"),
                })
        
        if rows:
            df = pd.DataFrame(rows)
            csv_path = output_dir / f"results_{scenario}.csv"
            df.to_csv(csv_path, index=False)
    
    console.print(f"\n[dim]Results saved to {output_dir}[/dim]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run retry amplification experiments")
    parser.add_argument(
        "--trials", 
        type=int, 
        default=100,
        help="Number of trials per configuration (default: 100)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick run with fewer trials (10 instead of 100)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="results/simulation/latest",
        help="Output directory for results"
    )
    
    args = parser.parse_args()
    
    num_trials = 10 if args.quick else args.trials
    
    start_time = datetime.now()
    console.print(f"[dim]Started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
    
    # Run experiments
    results = run_main_experiments(num_trials=num_trials, seed=args.seed)
    
    # Print tables
    print_table_3(results)
    print_table_5(results)
    print_table_6(results)
    calculate_reduction(results)
    
    # Save results
    output_dir = Path(__file__).resolve().parents[2] / args.output
    save_results(results, output_dir)
    
    end_time = datetime.now()
    duration = end_time - start_time
    console.print(f"\n[dim]Completed in {duration.total_seconds():.1f} seconds[/dim]")


if __name__ == "__main__":
    main()
