#!/usr/bin/env python3
"""
Analyze collected repositories for retry patterns.

This script:
1. Reads the repository list from collect_repositories.py
2. Downloads and analyzes each repository
3. Generates statistics matching the paper format

Usage:
    python experiments/analyze_collected_repos.py --input results/repository_list.json
"""

import os
import sys
import json
import tempfile
import zipfile
import urllib.request
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()


@dataclass
class RetryFinding:
    """A retry configuration found in code."""
    repo: str
    file: str
    line: int
    pattern: str
    max_retries: Optional[int] = None
    backoff_type: str = "unknown"
    has_jitter: bool = False
    evidence: str = ""


@dataclass
class RepoResult:
    """Analysis result for a repository."""
    name: str
    language: str
    stars: int
    files_analyzed: int = 0
    has_explicit_retry: bool = False
    retry_count: int = 0
    findings: list = field(default_factory=list)
    anti_patterns: list = field(default_factory=list)
    error: str = ""


class RetryAnalyzer:
    """Analyzes source code for retry patterns."""
    
    PATTERNS = {
        # Python patterns
        r'@retry\s*\(': ("python_decorator", r'\.py$'),
        r'Retry\s*\(\s*total\s*=\s*(\d+)': ("python_urllib3", r'\.py$'),
        r'@backoff\.(on_exception|on_predicate)': ("python_backoff", r'\.py$'),
        r'tenacity\.(retry|Retrying)': ("python_tenacity", r'\.py$'),
        r'max_retries\s*=\s*(\d+)': ("generic_max_retries", r'\.(py|go|java|js|ts)$'),
        
        # Go patterns
        r'RetryMax\s*[=:]\s*(\d+)': ("go_retry_max", r'\.go$'),
        r'Retry\s*{\s*Max\s*:\s*(\d+)': ("go_retry_struct", r'\.go$'),
        r'backoff\.Retry': ("go_backoff", r'\.go$'),
        r'ExponentialBackoff': ("go_exponential", r'\.go$'),
        
        # Java patterns  
        r'@Retryable\s*\(': ("java_retryable", r'\.java$'),
        r'RetryTemplate': ("java_spring_retry", r'\.java$'),
        r'Retry\.of\(': ("java_resilience4j", r'\.java$'),
        r'maxAttempts\s*=\s*(\d+)': ("java_max_attempts", r'\.java$'),
        
        # JavaScript/TypeScript patterns
        r'axios-retry': ("js_axios_retry", r'\.(js|ts)$'),
        r'retries\s*:\s*(\d+)': ("js_retries", r'\.(js|ts)$'),
        r'retry\s*:\s*{\s*limit': ("js_got_retry", r'\.(js|ts)$'),
    }
    
    def analyze_content(self, content: str, file_path: str, repo_name: str) -> list[RetryFinding]:
        """Analyze file content for retry patterns."""
        findings = []
        
        for pattern, (name, file_filter) in self.PATTERNS.items():
            if not re.search(file_filter, file_path, re.IGNORECASE):
                continue
            
            for match in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
                line = content[:match.start()].count('\n') + 1
                
                # Extract max retries if captured
                max_retries = None
                if match.groups():
                    try:
                        max_retries = int(match.group(1))
                    except (ValueError, IndexError):
                        pass
                
                # Check context for backoff/jitter
                ctx_start = max(0, match.start() - 200)
                ctx_end = min(len(content), match.end() + 200)
                context = content[ctx_start:ctx_end].lower()
                
                backoff_type = "none"
                if "exponential" in context:
                    backoff_type = "exponential"
                elif any(kw in context for kw in ["backoff", "delay", "wait"]):
                    backoff_type = "linear"
                
                has_jitter = "jitter" in context or "random" in context
                
                findings.append(RetryFinding(
                    repo=repo_name,
                    file=file_path,
                    line=line,
                    pattern=name,
                    max_retries=max_retries,
                    backoff_type=backoff_type,
                    has_jitter=has_jitter,
                    evidence=match.group(0)[:80],
                ))
        
        return findings


def download_repo(url: str, dest: Path) -> Optional[Path]:
    """Download and extract a repository."""
    try:
        # Convert GitHub URL to zip download URL
        if "github.com" in url:
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
                zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"
                
                zip_path = dest / "repo.zip"
                urllib.request.urlretrieve(zip_url, zip_path)
                
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(dest)
                
                # Find extracted directory
                for item in dest.iterdir():
                    if item.is_dir() and item.name != "__MACOSX":
                        return item
    except Exception as e:
        # Try master branch
        try:
            zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip"
            zip_path = dest / "repo.zip"
            urllib.request.urlretrieve(zip_path, zip_path)
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(dest)
            
            for item in dest.iterdir():
                if item.is_dir() and item.name != "__MACOSX":
                    return item
        except:
            pass
    
    return None


def analyze_repo(repo_info: dict, analyzer: RetryAnalyzer, temp_base: Path) -> RepoResult:
    """Analyze a single repository."""
    name = repo_info.get("full_name", "unknown")
    url = repo_info.get("url", "")
    language = repo_info.get("language", "Unknown")
    stars = repo_info.get("stars", 0)
    
    result = RepoResult(
        name=name,
        language=language,
        stars=stars,
    )
    
    # Create temp directory for this repo
    repo_temp = temp_base / name.replace("/", "_")
    repo_temp.mkdir(parents=True, exist_ok=True)
    
    try:
        repo_path = download_repo(url, repo_temp)
        if not repo_path:
            result.error = "Download failed"
            return result
        
        # Analyze files
        extensions = {'.py', '.go', '.java', '.js', '.ts'}
        skip_patterns = {'node_modules', 'vendor', '.git', 'test', '__pycache__', 'dist'}
        
        for file_path in repo_path.rglob('*'):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue
            if any(skip in str(file_path) for skip in skip_patterns):
                continue
            
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                result.files_analyzed += 1
                
                # Quick check for retry-related content
                if 'retry' in content.lower():
                    findings = analyzer.analyze_content(
                        content, 
                        str(file_path.relative_to(repo_path)),
                        name
                    )
                    result.findings.extend(findings)
                    
            except Exception:
                pass
        
        result.has_explicit_retry = len(result.findings) > 0
        result.retry_count = len(result.findings)
        
        # Detect anti-patterns
        for f in result.findings:
            if f.max_retries and f.max_retries > 5:
                result.anti_patterns.append("aggressive_retry")
            if f.backoff_type == "none":
                result.anti_patterns.append("no_backoff")
            if not f.has_jitter and f.backoff_type == "exponential":
                result.anti_patterns.append("missing_jitter")
        
        result.anti_patterns = list(set(result.anti_patterns))
        
    except Exception as e:
        result.error = str(e)
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze collected repositories")
    parser.add_argument(
        "--input",
        type=str,
        default="results/repositories/repository_list.json",
        help="Input repository list JSON"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="results/repositories/analysis_results.json",
        help="Output analysis results"
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="Maximum repos to analyze (for testing)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers"
    )
    
    args = parser.parse_args()
    
    # Load repository list
    input_path = Path(args.input)
    if not input_path.exists():
        console.print(f"[red]Input file not found: {input_path}[/red]")
        return 1
    
    with open(input_path) as f:
        data = json.load(f)
    
    repos = data.get("repositories", [])
    if args.max_repos:
        repos = repos[:args.max_repos]
    
    console.print(f"\n[bold blue]Analyzing {len(repos)} repositories for retry patterns[/bold blue]\n")
    
    analyzer = RetryAnalyzer()
    results: list[RepoResult] = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_base = Path(tmpdir)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            
            task = progress.add_task("[cyan]Analyzing...", total=len(repos))
            
            # Process sequentially for stability
            for repo in repos:
                name = repo.get("full_name", "unknown")
                progress.update(task, description=f"[cyan]{name[:35]}...")
                
                result = analyze_repo(repo, analyzer, temp_base)
                results.append(result)
                
                if result.has_explicit_retry:
                    console.print(f"  [green]✓ {name}[/green]: {result.retry_count} retry configs")
                
                progress.advance(task)
    
    # Calculate statistics
    console.print("\n" + "=" * 60)
    console.print("[bold]ANALYSIS RESULTS[/bold]")
    console.print("=" * 60)
    
    total = len(results)
    with_retry = sum(1 for r in results if r.has_explicit_retry)
    without_retry = total - with_retry
    
    all_findings = []
    for r in results:
        all_findings.extend(r.findings)
    
    # Table 1: Prevalence
    console.print("\n[bold]Table 1: Retry Implementation Prevalence[/bold]")
    table1 = Table()
    table1.add_column("Metric")
    table1.add_column("Value")
    table1.add_row("Projects with explicit retry logic", f"{with_retry}/{total} ({with_retry/total*100:.1f}%)")
    table1.add_row("Projects without retry handling", f"{without_retry}/{total} ({without_retry/total*100:.1f}%)")
    console.print(table1)
    
    # Table 2: Configuration distribution
    if all_findings:
        console.print("\n[bold]Table 2: Retry Configuration Distribution[/bold]")
        
        # Max retries
        r_1_3 = sum(1 for f in all_findings if f.max_retries and 1 <= f.max_retries <= 3)
        r_4_5 = sum(1 for f in all_findings if f.max_retries and 4 <= f.max_retries <= 5)
        r_over5 = sum(1 for f in all_findings if f.max_retries and f.max_retries > 5)
        total_with_count = r_1_3 + r_4_5 + r_over5
        
        # Backoff
        exp_backoff = sum(1 for f in all_findings if f.backoff_type == "exponential")
        lin_backoff = sum(1 for f in all_findings if f.backoff_type == "linear")
        no_backoff = sum(1 for f in all_findings if f.backoff_type == "none")
        total_backoff = exp_backoff + lin_backoff + no_backoff
        
        # Jitter
        with_jitter = sum(1 for f in all_findings if f.has_jitter)
        
        table2 = Table()
        table2.add_column("Configuration")
        table2.add_column("Frequency")
        
        if total_with_count > 0:
            table2.add_row("Retry count: 1-3", f"{r_1_3/total_with_count*100:.1f}%")
            table2.add_row("Retry count: 4-5", f"{r_4_5/total_with_count*100:.1f}%")
            table2.add_row("Retry count: >5", f"{r_over5/total_with_count*100:.1f}%")
        
        if total_backoff > 0:
            table2.add_row("Exponential backoff", f"{exp_backoff/total_backoff*100:.1f}%")
            table2.add_row("Linear backoff", f"{lin_backoff/total_backoff*100:.1f}%")
            table2.add_row("No backoff (immediate)", f"{no_backoff/total_backoff*100:.1f}%")
            table2.add_row("Jitter implemented", f"{with_jitter/len(all_findings)*100:.1f}%")
        
        console.print(table2)
    
    # Anti-patterns
    all_anti = []
    for r in results:
        all_anti.extend(r.anti_patterns)
    
    if all_anti:
        console.print("\n[bold]Anti-Patterns Detected[/bold]")
        ap_counts = defaultdict(int)
        for ap in all_anti:
            ap_counts[ap] += 1
        
        table3 = Table()
        table3.add_column("Anti-Pattern")
        table3.add_column("Repos Affected")
        
        for ap, count in sorted(ap_counts.items(), key=lambda x: -x[1]):
            pct = count / with_retry * 100 if with_retry > 0 else 0
            table3.add_row(ap.replace("_", " ").title(), f"{count} ({pct:.1f}%)")
        
        console.print(table3)
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        "analysis_date": str(Path(args.input).stat().st_mtime),
        "total_repositories": total,
        "repositories_with_retry": with_retry,
        "total_retry_configs": len(all_findings),
        "statistics": {
            "prevalence_with_retry": with_retry / total if total > 0 else 0,
            "retry_count_1_3": r_1_3 / total_with_count if total_with_count > 0 else 0,
            "retry_count_4_5": r_4_5 / total_with_count if total_with_count > 0 else 0,
            "retry_count_over_5": r_over5 / total_with_count if total_with_count > 0 else 0,
            "exponential_backoff": exp_backoff / total_backoff if total_backoff > 0 else 0,
            "linear_backoff": lin_backoff / total_backoff if total_backoff > 0 else 0,
            "no_backoff": no_backoff / total_backoff if total_backoff > 0 else 0,
            "has_jitter": with_jitter / len(all_findings) if all_findings else 0,
        },
        "findings": [asdict(f) for f in all_findings[:1000]],  # Limit for file size
        "repositories": [
            {
                "name": r.name,
                "language": r.language,
                "has_retry": r.has_explicit_retry,
                "retry_count": r.retry_count,
                "anti_patterns": r.anti_patterns,
            }
            for r in results
        ]
    }
    
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    
    console.print(f"\n[dim]Results saved to {output_path}[/dim]")
    console.print(f"\n[bold green]✓ Analyzed {total} repositories, found {len(all_findings)} retry configurations[/bold green]")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
