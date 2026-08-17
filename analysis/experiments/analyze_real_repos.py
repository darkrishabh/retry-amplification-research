#!/usr/bin/env python3
"""
Proof-of-Concept: Analyze real open-source repositories for retry patterns.

This script demonstrates the methodology by:
1. Downloading well-known microservice projects
2. Analyzing their retry configurations
3. Generating verifiable statistics

No GitHub token required - uses direct HTTP downloads.
"""

import os
import sys
import re
import json
import tempfile
import zipfile
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich.progress import Progress

console = Console()


# Well-known open-source microservice projects to analyze
# These are real projects we can verify
SAMPLE_REPOS = [
    # Python projects
    ("httpbin", "https://github.com/postmanlabs/httpbin/archive/refs/heads/master.zip", "Python"),
    ("sentry", "https://github.com/getsentry/sentry/archive/refs/heads/master.zip", "Python"),
    ("locust", "https://github.com/locustio/locust/archive/refs/heads/master.zip", "Python"),
    
    # Go projects  
    ("traefik", "https://github.com/traefik/traefik/archive/refs/heads/master.zip", "Go"),
    ("consul", "https://github.com/hashicorp/consul/archive/refs/heads/main.zip", "Go"),
    ("prometheus", "https://github.com/prometheus/prometheus/archive/refs/heads/main.zip", "Go"),
    
    # JavaScript/TypeScript projects
    ("strapi", "https://github.com/strapi/strapi/archive/refs/heads/main.zip", "JavaScript"),
    ("nest", "https://github.com/nestjs/nest/archive/refs/heads/master.zip", "TypeScript"),
    
    # Java projects
    ("spring-cloud-netflix", "https://github.com/spring-cloud/spring-cloud-netflix/archive/refs/heads/main.zip", "Java"),
]


@dataclass
class RetryFinding:
    """A single retry configuration found in code."""
    file: str
    line_number: int
    pattern_type: str
    raw_match: str
    max_retries: Optional[int] = None
    has_backoff: bool = False
    backoff_type: str = "unknown"  # none, linear, exponential
    has_jitter: bool = False
    
    def to_dict(self):
        return {
            "file": self.file,
            "line": self.line_number,
            "type": self.pattern_type,
            "max_retries": self.max_retries,
            "backoff_type": self.backoff_type,
            "has_jitter": self.has_jitter,
            "evidence": self.raw_match[:100],
        }


class RetryAnalyzer:
    """Analyzes source code for retry patterns with evidence."""
    
    # Regex patterns to find retry configurations
    PATTERNS = {
        # Python
        "python_retry_decorator": (
            r'@retry\s*\([^)]*\)',
            r'\.py$'
        ),
        "python_tenacity": (
            r'@retry\s*\(\s*(?:stop\s*=\s*stop_after_attempt\s*\(\s*(\d+)|wait\s*=)',
            r'\.py$'
        ),
        "python_urllib3_retry": (
            r'Retry\s*\(\s*(?:total\s*=\s*(\d+)|connect\s*=)',
            r'\.py$'
        ),
        "python_requests_retry": (
            r'HTTPAdapter\s*\([^)]*max_retries',
            r'\.py$'
        ),
        "python_backoff": (
            r'@backoff\.(on_exception|on_predicate)',
            r'\.py$'
        ),
        
        # Go
        "go_retry_config": (
            r'(?:Retry|retry)(?:Max|Count|Attempts?)\s*[=:]\s*(\d+)',
            r'\.go$'
        ),
        "go_backoff": (
            r'(?:backoff|Backoff)\s*[=:.]',
            r'\.go$'
        ),
        "go_exponential": (
            r'ExponentialBackoff|exponential_backoff',
            r'\.go$'
        ),
        
        # JavaScript/TypeScript
        "js_axios_retry": (
            r'axios-retry|axiosRetry',
            r'\.(js|ts)$'
        ),
        "js_retry_config": (
            r'retries?\s*[=:]\s*(\d+)',
            r'\.(js|ts)$'
        ),
        "js_got_retry": (
            r'retry\s*:\s*\{',
            r'\.(js|ts)$'
        ),
        
        # Java
        "java_retryable": (
            r'@Retryable\s*\([^)]*maxAttempts\s*=\s*(\d+)',
            r'\.java$'
        ),
        "java_resilience4j": (
            r'Retry\.of|RetryConfig\.custom',
            r'\.java$'
        ),
        "java_spring_retry": (
            r'RetryTemplate|@EnableRetry',
            r'\.java$'
        ),
    }
    
    def __init__(self):
        self.findings: list[RetryFinding] = []
        self.files_analyzed = 0
        self.files_with_retry = 0
    
    def analyze_file(self, file_path: Path, content: str) -> list[RetryFinding]:
        """Analyze a single file for retry patterns."""
        findings = []
        file_str = str(file_path)
        
        for pattern_name, (regex, file_pattern) in self.PATTERNS.items():
            if not re.search(file_pattern, file_str, re.IGNORECASE):
                continue
            
            for match in re.finditer(regex, content, re.MULTILINE | re.IGNORECASE):
                # Calculate line number
                line_num = content[:match.start()].count('\n') + 1
                
                # Extract max retries if captured
                max_retries = None
                if match.groups():
                    try:
                        max_retries = int(match.group(1)) if match.group(1) else None
                    except (ValueError, IndexError):
                        pass
                
                # Check surrounding context for backoff/jitter
                context_start = max(0, match.start() - 300)
                context_end = min(len(content), match.end() + 300)
                context = content[context_start:context_end].lower()
                
                has_backoff = any(kw in context for kw in ['backoff', 'delay', 'wait', 'sleep'])
                has_jitter = any(kw in context for kw in ['jitter', 'random'])
                
                backoff_type = "none"
                if 'exponential' in context:
                    backoff_type = "exponential"
                elif has_backoff:
                    backoff_type = "linear"
                
                finding = RetryFinding(
                    file=str(file_path),
                    line_number=line_num,
                    pattern_type=pattern_name,
                    raw_match=match.group(0),
                    max_retries=max_retries,
                    has_backoff=has_backoff,
                    backoff_type=backoff_type,
                    has_jitter=has_jitter,
                )
                findings.append(finding)
        
        return findings
    
    def analyze_directory(self, dir_path: Path) -> list[RetryFinding]:
        """Analyze all code files in a directory."""
        findings = []
        
        extensions = {'.py', '.go', '.js', '.ts', '.java', '.kt'}
        skip_dirs = {'node_modules', 'vendor', '.git', 'test', 'tests', '__pycache__', 'dist', 'build'}
        
        for file_path in dir_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            if file_path.suffix.lower() not in extensions:
                continue
            
            # Skip test/vendor directories
            if any(skip in file_path.parts for skip in skip_dirs):
                continue
            
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                self.files_analyzed += 1
                
                file_findings = self.analyze_file(file_path, content)
                if file_findings:
                    self.files_with_retry += 1
                    findings.extend(file_findings)
                    
            except Exception as e:
                pass
        
        return findings


def download_and_extract(url: str, extract_to: Path) -> Optional[Path]:
    """Download a zip file and extract it."""
    try:
        # Download
        zip_path = extract_to / "repo.zip"
        urllib.request.urlretrieve(url, zip_path)
        
        # Extract
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        
        # Find the extracted directory
        for item in extract_to.iterdir():
            if item.is_dir() and item.name != "__MACOSX":
                return item
        
        return None
    except Exception as e:
        console.print(f"[red]Failed to download: {e}[/red]")
        return None


def main():
    """Run the proof-of-concept analysis."""
    
    console.print("\n[bold blue]═══════════════════════════════════════════════════════════════[/bold blue]")
    console.print("[bold blue]  Retry Pattern Analysis - Proof of Concept with Real Repositories[/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════════════════════════════[/bold blue]\n")
    
    all_findings = []
    repo_stats = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        with Progress(console=console) as progress:
            task = progress.add_task("[cyan]Analyzing repositories...", total=len(SAMPLE_REPOS))
            
            for repo_name, url, language in SAMPLE_REPOS:
                progress.update(task, description=f"[cyan]Analyzing {repo_name}...")
                
                # Download and extract
                repo_dir = tmppath / repo_name
                repo_dir.mkdir(exist_ok=True)
                
                extracted = download_and_extract(url, repo_dir)
                
                if extracted:
                    # Analyze
                    analyzer = RetryAnalyzer()
                    findings = analyzer.analyze_directory(extracted)
                    
                    all_findings.extend(findings)
                    
                    repo_stats.append({
                        "name": repo_name,
                        "language": language,
                        "files_analyzed": analyzer.files_analyzed,
                        "files_with_retry": analyzer.files_with_retry,
                        "retry_configs_found": len(findings),
                        "has_explicit_retry": len(findings) > 0,
                    })
                    
                    # Show findings for this repo
                    if findings:
                        console.print(f"\n[green]✓ {repo_name}[/green]: Found {len(findings)} retry configurations")
                        for f in findings[:3]:  # Show first 3
                            console.print(f"  [dim]• {Path(f.file).name}:{f.line_number} - {f.pattern_type}[/dim]")
                            console.print(f"    [dim italic]\"{f.raw_match[:60]}...\"[/dim italic]")
                    else:
                        console.print(f"\n[yellow]○ {repo_name}[/yellow]: No explicit retry found")
                
                progress.advance(task)
    
    # Generate statistics
    console.print("\n" + "═" * 65)
    console.print("[bold]ANALYSIS RESULTS - Verifiable Data from Real Repositories[/bold]")
    console.print("═" * 65 + "\n")
    
    # Summary table
    table = Table(title="Repository Analysis Summary", show_header=True, header_style="bold magenta")
    table.add_column("Repository")
    table.add_column("Language")
    table.add_column("Files Analyzed")
    table.add_column("Retry Configs")
    table.add_column("Has Retry?")
    
    for stat in repo_stats:
        table.add_row(
            stat["name"],
            stat["language"],
            str(stat["files_analyzed"]),
            str(stat["retry_configs_found"]),
            "✓" if stat["has_explicit_retry"] else "✗",
        )
    
    console.print(table)
    
    # Aggregate statistics (matching paper format)
    total_repos = len(repo_stats)
    repos_with_retry = sum(1 for s in repo_stats if s["has_explicit_retry"])
    repos_without_retry = total_repos - repos_with_retry
    
    console.print("\n[bold]Prevalence Statistics (Paper Table 1 Format):[/bold]")
    console.print(f"  • Projects with explicit retry logic: {repos_with_retry}/{total_repos} ({repos_with_retry/total_repos*100:.1f}%)")
    console.print(f"  • Projects without retry handling: {repos_without_retry}/{total_repos} ({repos_without_retry/total_repos*100:.1f}%)")
    
    # Retry configuration breakdown
    if all_findings:
        console.print("\n[bold]Configuration Analysis (Paper Table 2 Format):[/bold]")
        
        # Max retries distribution
        retries_1_3 = sum(1 for f in all_findings if f.max_retries and 1 <= f.max_retries <= 3)
        retries_4_5 = sum(1 for f in all_findings if f.max_retries and 4 <= f.max_retries <= 5)
        retries_over_5 = sum(1 for f in all_findings if f.max_retries and f.max_retries > 5)
        retries_unknown = sum(1 for f in all_findings if f.max_retries is None)
        
        total_with_count = retries_1_3 + retries_4_5 + retries_over_5
        if total_with_count > 0:
            console.print(f"  • Retry count 1-3: {retries_1_3/total_with_count*100:.1f}%")
            console.print(f"  • Retry count 4-5: {retries_4_5/total_with_count*100:.1f}%")
            console.print(f"  • Retry count >5: {retries_over_5/total_with_count*100:.1f}%")
        
        # Backoff analysis
        exponential = sum(1 for f in all_findings if f.backoff_type == "exponential")
        linear = sum(1 for f in all_findings if f.backoff_type == "linear")
        no_backoff = sum(1 for f in all_findings if f.backoff_type == "none")
        
        total_backoff = exponential + linear + no_backoff
        if total_backoff > 0:
            console.print(f"  • Exponential backoff: {exponential/total_backoff*100:.1f}%")
            console.print(f"  • Linear backoff: {linear/total_backoff*100:.1f}%")
            console.print(f"  • No backoff: {no_backoff/total_backoff*100:.1f}%")
        
        # Jitter
        with_jitter = sum(1 for f in all_findings if f.has_jitter)
        console.print(f"  • Jitter implemented: {with_jitter/len(all_findings)*100:.1f}%")
    
    # Save detailed results
    output_dir = Path(__file__).resolve().parents[2] / "results" / "repositories" / "proof-of-concept"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / "findings.json", "w") as f:
        json.dump([finding.to_dict() for finding in all_findings], f, indent=2)
    
    with open(output_dir / "repo_stats.json", "w") as f:
        json.dump(repo_stats, f, indent=2)
    
    console.print(f"\n[dim]Detailed findings saved to {output_dir}[/dim]")
    console.print("\n[bold green]✓ Analysis complete - all data is verifiable from real repositories[/bold green]\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
