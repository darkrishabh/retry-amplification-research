#!/usr/bin/env python3
"""
GitHub Repository Analyzer for Retry Pattern Detection.

This tool:
1. Searches GitHub for microservice repositories matching criteria
2. Clones/downloads repositories
3. Analyzes code for retry configurations
4. Extracts retry patterns and generates statistics

Requirements:
    pip install PyGithub gitpython

Usage:
    python -m src.analysis.github_analyzer --token YOUR_GITHUB_TOKEN
"""

import os
import re
import json
import argparse
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Generator
from datetime import datetime, timedelta
from collections import defaultdict

try:
    from github import Github, RateLimitExceededException
    from github.Repository import Repository
except ImportError:
    print("Please install PyGithub: pip install PyGithub")
    Github = None

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

console = Console()


@dataclass
class RetryConfig:
    """Extracted retry configuration from code."""
    
    file_path: str
    language: str
    library: str  # e.g., axios, requests, grpc
    
    # Retry parameters
    max_retries: Optional[int] = None
    backoff_type: str = "unknown"  # none, linear, exponential
    has_jitter: bool = False
    initial_delay_ms: Optional[int] = None
    max_delay_ms: Optional[int] = None
    timeout_ms: Optional[int] = None
    
    # Retry conditions
    retry_on_all_errors: bool = False
    retryable_status_codes: list = field(default_factory=list)
    
    # Anti-patterns detected
    anti_patterns: list = field(default_factory=list)
    
    # Raw match for verification
    raw_match: str = ""


@dataclass 
class RepoAnalysis:
    """Analysis results for a single repository."""
    
    repo_name: str
    repo_url: str
    stars: int
    language: str
    description: str = ""
    
    # Retry configurations found
    retry_configs: list = field(default_factory=list)
    
    # Summary
    has_explicit_retry: bool = False
    has_library_default_retry: bool = False
    retry_count: int = 0
    
    # Anti-patterns
    anti_patterns_found: list = field(default_factory=list)


class RetryPatternDetector:
    """Detects retry patterns in source code."""
    
    # Pattern definitions for different languages/libraries
    PATTERNS = {
        "python": {
            "requests": [
                # requests with retry adapter
                (r'Retry\s*\(\s*total\s*=\s*(\d+)', "max_retries"),
                (r'backoff_factor\s*=\s*([\d.]+)', "backoff_factor"),
                (r'status_forcelist\s*=\s*\[([\d,\s]+)\]', "status_codes"),
            ],
            "urllib3": [
                (r'Retry\s*\(\s*total\s*=\s*(\d+)', "max_retries"),
                (r'connect\s*=\s*(\d+)', "connect_retries"),
                (r'backoff_factor\s*=\s*([\d.]+)', "backoff_factor"),
            ],
            "tenacity": [
                (r'stop_after_attempt\s*\(\s*(\d+)\s*\)', "max_retries"),
                (r'wait_exponential', "exponential_backoff"),
                (r'wait_fixed\s*\(\s*(\d+)\s*\)', "fixed_delay"),
                (r'wait_random', "jitter"),
            ],
            "aiohttp": [
                (r'retry_options\s*=.*max_tries\s*=\s*(\d+)', "max_retries"),
            ],
            "grpc": [
                (r'max_retries\s*=\s*(\d+)', "max_retries"),
                (r'initial_backoff\s*=\s*([\d.]+)', "initial_backoff"),
                (r'max_backoff\s*=\s*([\d.]+)', "max_backoff"),
            ],
        },
        "javascript": {
            "axios": [
                (r'axios-retry.*retries\s*:\s*(\d+)', "max_retries"),
                (r'retryDelay\s*:\s*(\d+)', "retry_delay"),
                (r'exponentialDelay', "exponential_backoff"),
                (r'retryCondition', "custom_condition"),
            ],
            "fetch": [
                (r'retry\s*[=:]\s*(\d+)', "max_retries"),
                (r'retries\s*[=:]\s*(\d+)', "max_retries"),
            ],
            "got": [
                (r'retry\s*:\s*\{[^}]*limit\s*:\s*(\d+)', "max_retries"),
                (r'calculateDelay', "custom_backoff"),
            ],
            "node-fetch": [
                (r'retry\s*:\s*(\d+)', "max_retries"),
            ],
            "grpc": [
                (r'maxRetries\s*:\s*(\d+)', "max_retries"),
                (r'initialBackoffMs\s*:\s*(\d+)', "initial_backoff"),
            ],
        },
        "go": {
            "http": [
                (r'Retry\s*=\s*(\d+)', "max_retries"),
                (r'MaxRetries\s*:\s*(\d+)', "max_retries"),
                (r'RetryMax\s*:\s*(\d+)', "max_retries"),
                (r'Backoff\s*:', "has_backoff"),
                (r'ExponentialBackoff', "exponential_backoff"),
            ],
            "grpc": [
                (r'MaxRetries\s*:\s*(\d+)', "max_retries"),
                (r'InitialBackoff\s*:', "initial_backoff"),
                (r'MaxBackoff\s*:', "max_backoff"),
                (r'BackoffMultiplier\s*:', "backoff_multiplier"),
            ],
            "hashicorp-retryablehttp": [
                (r'RetryMax\s*=\s*(\d+)', "max_retries"),
                (r'RetryWaitMin\s*=', "min_wait"),
                (r'RetryWaitMax\s*=', "max_wait"),
            ],
        },
        "java": {
            "spring-retry": [
                (r'@Retryable.*maxAttempts\s*=\s*(\d+)', "max_retries"),
                (r'backoff\s*=\s*@Backoff', "has_backoff"),
                (r'delay\s*=\s*(\d+)', "delay"),
                (r'multiplier\s*=\s*([\d.]+)', "multiplier"),
            ],
            "resilience4j": [
                (r'maxAttempts\s*\(\s*(\d+)\s*\)', "max_retries"),
                (r'waitDuration\s*\([^)]+\)', "wait_duration"),
                (r'exponentialBackoff', "exponential_backoff"),
            ],
            "okhttp": [
                (r'retryOnConnectionFailure\s*\(\s*(true|false)\s*\)', "retry_on_failure"),
            ],
            "grpc": [
                (r'maxRetryAttempts\s*\(\s*(\d+)\s*\)', "max_retries"),
                (r'initialBackoff\s*\([^)]+\)', "initial_backoff"),
            ],
        },
        "typescript": {
            # Same as JavaScript
            "axios": [
                (r'axios-retry.*retries\s*:\s*(\d+)', "max_retries"),
                (r'retryDelay\s*:\s*(\d+)', "retry_delay"),
                (r'exponentialDelay', "exponential_backoff"),
            ],
            "fetch": [
                (r'retry\s*[=:]\s*(\d+)', "max_retries"),
                (r'retries\s*[=:]\s*(\d+)', "max_retries"),
            ],
        },
    }
    
    # Anti-pattern detection rules
    ANTI_PATTERNS = {
        "aggressive_retry": r'(?:retries?|maxRetries|max_retries|RetryMax)\s*[=:]\s*([5-9]|\d{2,})',
        "no_backoff": r'(?:retries?|maxRetries)\s*[=:]\s*\d+(?!.*(?:backoff|delay|wait))',
        "retry_all_errors": r'(?:retryOnAllErrors|retry_on_all|shouldRetry.*true)',
        "immediate_retry": r'(?:delay|wait|backoff)\s*[=:]\s*0\b',
        "no_jitter": r'exponential(?!.*(?:jitter|random))',
    }
    
    def __init__(self):
        self.stats = defaultdict(int)
    
    def analyze_file(self, file_path: Path, content: str) -> list[RetryConfig]:
        """Analyze a single file for retry configurations."""
        configs = []
        
        # Determine language from extension
        ext = file_path.suffix.lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".go": "go",
            ".java": "java",
            ".kt": "java",  # Kotlin uses similar patterns
        }
        
        language = lang_map.get(ext)
        if not language:
            return configs
        
        # Get patterns for this language
        lang_patterns = self.PATTERNS.get(language, {})
        
        for library, patterns in lang_patterns.items():
            for pattern, param_type in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    config = self._extract_config(
                        file_path, language, library, pattern, param_type, match, content
                    )
                    if config:
                        configs.append(config)
        
        # Check for anti-patterns
        for config in configs:
            config.anti_patterns = self._detect_anti_patterns(content)
        
        return configs
    
    def _extract_config(
        self, 
        file_path: Path, 
        language: str, 
        library: str,
        pattern: str,
        param_type: str,
        match: re.Match,
        content: str
    ) -> Optional[RetryConfig]:
        """Extract retry configuration from a regex match."""
        
        config = RetryConfig(
            file_path=str(file_path),
            language=language,
            library=library,
            raw_match=match.group(0)[:200],  # First 200 chars
        )
        
        # Extract the matched value
        try:
            if match.groups():
                value = match.group(1)
                
                if param_type == "max_retries":
                    config.max_retries = int(value)
                elif param_type == "backoff_factor":
                    config.backoff_type = "exponential"
                elif param_type == "exponential_backoff":
                    config.backoff_type = "exponential"
                elif param_type == "fixed_delay":
                    config.backoff_type = "linear"
                    config.initial_delay_ms = int(value)
                elif param_type == "jitter":
                    config.has_jitter = True
                elif param_type in ("initial_backoff", "delay"):
                    config.initial_delay_ms = int(float(value) * 1000) if "." in value else int(value)
        except (ValueError, IndexError):
            pass
        
        # Look for jitter in surrounding context
        context_start = max(0, match.start() - 200)
        context_end = min(len(content), match.end() + 200)
        context = content[context_start:context_end].lower()
        
        if "jitter" in context or "random" in context:
            config.has_jitter = True
        
        if "exponential" in context:
            config.backoff_type = "exponential"
        elif "linear" in context or "fixed" in context:
            config.backoff_type = "linear"
        
        return config
    
    def _detect_anti_patterns(self, content: str) -> list[str]:
        """Detect anti-patterns in code."""
        detected = []
        
        for name, pattern in self.ANTI_PATTERNS.items():
            if re.search(pattern, content, re.IGNORECASE):
                detected.append(name)
        
        return detected
    
    def analyze_repository(self, repo_path: Path) -> list[RetryConfig]:
        """Analyze all relevant files in a repository."""
        configs = []
        
        extensions = {".py", ".js", ".ts", ".go", ".java", ".kt"}
        
        for ext in extensions:
            for file_path in repo_path.rglob(f"*{ext}"):
                # Skip test files and node_modules
                path_str = str(file_path).lower()
                if any(skip in path_str for skip in ["test", "node_modules", "vendor", ".git"]):
                    continue
                
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    file_configs = self.analyze_file(file_path, content)
                    configs.extend(file_configs)
                except Exception as e:
                    pass  # Skip files that can't be read
        
        return configs


class GitHubAnalyzer:
    """Analyzes GitHub repositories for retry patterns."""
    
    def __init__(self, token: str):
        if Github is None:
            raise ImportError("PyGithub is required. Install with: pip install PyGithub")
        
        self.github = Github(token)
        self.detector = RetryPatternDetector()
        self.results: list[RepoAnalysis] = []
    
    def search_repositories(
        self,
        languages: list[str] = None,
        min_stars: int = 50,
        keywords: list[str] = None,
        max_repos: int = 100,
    ) -> Generator[Repository, None, None]:
        """
        Search GitHub for microservice repositories.
        
        Args:
            languages: List of programming languages to search
            min_stars: Minimum star count
            keywords: Keywords to search in description/README
            max_repos: Maximum number of repos to return
        """
        if languages is None:
            languages = ["Python", "JavaScript", "TypeScript", "Go", "Java"]
        
        if keywords is None:
            keywords = ["microservice", "distributed"]
        
        # Calculate date for "active in past 12 months"
        one_year_ago = datetime.now() - timedelta(days=365)
        date_filter = one_year_ago.strftime("%Y-%m-%d")
        
        repos_found = 0
        
        for language in languages:
            for keyword in keywords:
                if repos_found >= max_repos:
                    return
                
                query = f"{keyword} language:{language} stars:>={min_stars} pushed:>={date_filter}"
                
                try:
                    results = self.github.search_repositories(
                        query=query,
                        sort="stars",
                        order="desc"
                    )
                    
                    for repo in results:
                        if repos_found >= max_repos:
                            return
                        
                        yield repo
                        repos_found += 1
                        
                except RateLimitExceededException:
                    console.print("[yellow]Rate limit reached. Waiting...[/yellow]")
                    import time
                    time.sleep(60)
                except Exception as e:
                    console.print(f"[red]Error searching: {e}[/red]")
    
    def analyze_repo_content(self, repo: Repository) -> RepoAnalysis:
        """Analyze a repository's content for retry patterns."""
        
        analysis = RepoAnalysis(
            repo_name=repo.full_name,
            repo_url=repo.html_url,
            stars=repo.stargazers_count,
            language=repo.language or "unknown",
            description=repo.description or "",
        )
        
        # Download and analyze repo content
        try:
            # Get default branch content via API (no clone needed)
            configs = self._analyze_repo_via_api(repo)
            analysis.retry_configs = [asdict(c) for c in configs]
            analysis.retry_count = len(configs)
            analysis.has_explicit_retry = len(configs) > 0
            
            # Collect anti-patterns
            all_anti_patterns = set()
            for config in configs:
                all_anti_patterns.update(config.anti_patterns)
            analysis.anti_patterns_found = list(all_anti_patterns)
            
        except Exception as e:
            console.print(f"[dim]Error analyzing {repo.full_name}: {e}[/dim]")
        
        return analysis
    
    def _analyze_repo_via_api(self, repo: Repository, max_files: int = 50) -> list[RetryConfig]:
        """Analyze repository using GitHub API (no cloning)."""
        configs = []
        files_analyzed = 0
        
        # File patterns to look for
        interesting_patterns = [
            "retry", "client", "http", "grpc", "api", "service", "request"
        ]
        
        try:
            # Get repository tree
            default_branch = repo.default_branch
            tree = repo.get_git_tree(default_branch, recursive=True)
            
            for item in tree.tree:
                if files_analyzed >= max_files:
                    break
                
                if item.type != "blob":
                    continue
                
                path = item.path.lower()
                
                # Skip non-code files
                if not any(path.endswith(ext) for ext in [".py", ".js", ".ts", ".go", ".java"]):
                    continue
                
                # Skip test/vendor files
                if any(skip in path for skip in ["test", "node_modules", "vendor", ".git"]):
                    continue
                
                # Prioritize files likely to contain retry logic
                is_interesting = any(p in path for p in interesting_patterns)
                
                if is_interesting or files_analyzed < 20:
                    try:
                        blob = repo.get_git_blob(item.sha)
                        import base64
                        content = base64.b64decode(blob.content).decode("utf-8", errors="ignore")
                        
                        # Quick check if file mentions retry
                        if "retry" in content.lower():
                            file_configs = self.detector.analyze_file(Path(item.path), content)
                            configs.extend(file_configs)
                        
                        files_analyzed += 1
                        
                    except Exception:
                        pass
                        
        except Exception as e:
            pass
        
        return configs
    
    def run_analysis(
        self,
        max_repos: int = 100,
        output_path: Optional[Path] = None,
    ) -> dict:
        """
        Run the full analysis pipeline.
        
        Returns aggregated statistics.
        """
        console.print("\n[bold blue]GitHub Repository Retry Pattern Analysis[/bold blue]\n")
        
        stats = {
            "total_repos_searched": 0,
            "repos_with_explicit_retry": 0,
            "repos_with_library_default": 0,
            "repos_without_retry": 0,
            "retry_configs": {
                "count_1_3": 0,
                "count_4_5": 0,
                "count_over_5": 0,
                "exponential_backoff": 0,
                "linear_backoff": 0,
                "no_backoff": 0,
                "has_jitter": 0,
            },
            "anti_patterns": defaultdict(int),
            "by_language": defaultdict(int),
            "by_library": defaultdict(int),
        }
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            
            task = progress.add_task("[cyan]Analyzing repositories...", total=max_repos)
            
            for repo in self.search_repositories(max_repos=max_repos):
                progress.update(task, description=f"[cyan]{repo.full_name[:40]}...")
                
                analysis = self.analyze_repo_content(repo)
                self.results.append(analysis)
                
                # Update stats
                stats["total_repos_searched"] += 1
                stats["by_language"][analysis.language] += 1
                
                if analysis.has_explicit_retry:
                    stats["repos_with_explicit_retry"] += 1
                else:
                    stats["repos_without_retry"] += 1
                
                # Analyze retry configs
                for config in analysis.retry_configs:
                    # Max retries distribution
                    max_retries = config.get("max_retries")
                    if max_retries:
                        if 1 <= max_retries <= 3:
                            stats["retry_configs"]["count_1_3"] += 1
                        elif 4 <= max_retries <= 5:
                            stats["retry_configs"]["count_4_5"] += 1
                        elif max_retries > 5:
                            stats["retry_configs"]["count_over_5"] += 1
                    
                    # Backoff type
                    backoff = config.get("backoff_type", "unknown")
                    if backoff == "exponential":
                        stats["retry_configs"]["exponential_backoff"] += 1
                    elif backoff == "linear":
                        stats["retry_configs"]["linear_backoff"] += 1
                    elif backoff in ("none", "unknown"):
                        stats["retry_configs"]["no_backoff"] += 1
                    
                    # Jitter
                    if config.get("has_jitter"):
                        stats["retry_configs"]["has_jitter"] += 1
                    
                    # Library
                    stats["by_library"][config.get("library", "unknown")] += 1
                
                # Anti-patterns
                for ap in analysis.anti_patterns_found:
                    stats["anti_patterns"][ap] += 1
                
                progress.advance(task)
        
        # Convert defaultdicts to regular dicts for JSON serialization
        stats["anti_patterns"] = dict(stats["anti_patterns"])
        stats["by_language"] = dict(stats["by_language"])
        stats["by_library"] = dict(stats["by_library"])
        
        # Save results
        if output_path:
            output_path.mkdir(parents=True, exist_ok=True)
            
            with open(output_path / "analysis_stats.json", "w") as f:
                json.dump(stats, f, indent=2)
            
            with open(output_path / "repo_analyses.json", "w") as f:
                json.dump([asdict(r) if hasattr(r, '__dataclass_fields__') else r 
                          for r in self.results], f, indent=2, default=str)
            
            console.print(f"\n[dim]Results saved to {output_path}[/dim]")
        
        return stats
    
    def print_summary(self, stats: dict):
        """Print a summary table matching the paper format."""
        
        console.print("\n[bold]Table 1: Retry Implementation Prevalence[/bold]")
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric")
        table.add_column("Value")
        
        total = stats["total_repos_searched"]
        explicit = stats["repos_with_explicit_retry"]
        no_retry = stats["repos_without_retry"]
        
        table.add_row(
            "Projects with explicit retry logic",
            f"{explicit}/{total} ({explicit/total*100:.1f}%)" if total > 0 else "N/A"
        )
        table.add_row(
            "Projects with no retry handling",
            f"{no_retry}/{total} ({no_retry/total*100:.1f}%)" if total > 0 else "N/A"
        )
        
        console.print(table)
        
        # Retry configuration distribution
        console.print("\n[bold]Table 2: Retry Configuration Distribution[/bold]")
        
        table2 = Table(show_header=True, header_style="bold magenta")
        table2.add_column("Configuration")
        table2.add_column("Frequency")
        
        rc = stats["retry_configs"]
        total_configs = sum([rc["count_1_3"], rc["count_4_5"], rc["count_over_5"]])
        
        if total_configs > 0:
            table2.add_row("Retry count: 1-3", f"{rc['count_1_3']/total_configs*100:.1f}%")
            table2.add_row("Retry count: 4-5", f"{rc['count_4_5']/total_configs*100:.1f}%")
            table2.add_row("Retry count: >5", f"{rc['count_over_5']/total_configs*100:.1f}%")
            
            backoff_total = rc["exponential_backoff"] + rc["linear_backoff"] + rc["no_backoff"]
            if backoff_total > 0:
                table2.add_row("Exponential backoff", f"{rc['exponential_backoff']/backoff_total*100:.1f}%")
                table2.add_row("Linear backoff", f"{rc['linear_backoff']/backoff_total*100:.1f}%")
                table2.add_row("No backoff (immediate)", f"{rc['no_backoff']/backoff_total*100:.1f}%")
                table2.add_row("Jitter implemented", f"{rc['has_jitter']/backoff_total*100:.1f}%")
        
        console.print(table2)
        
        # Anti-patterns
        if stats["anti_patterns"]:
            console.print("\n[bold]Detected Anti-Patterns[/bold]")
            
            table3 = Table(show_header=True, header_style="bold magenta")
            table3.add_column("Anti-Pattern")
            table3.add_column("Occurrences")
            
            for ap, count in sorted(stats["anti_patterns"].items(), key=lambda x: -x[1]):
                table3.add_row(ap.replace("_", " ").title(), str(count))
            
            console.print(table3)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze GitHub repos for retry patterns")
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub API token (or set GITHUB_TOKEN env var)"
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=100,
        help="Maximum repositories to analyze"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="results/github_analysis",
        help="Output directory for results"
    )
    
    args = parser.parse_args()
    
    if not args.token:
        console.print("[red]GitHub token required. Set GITHUB_TOKEN or use --token[/red]")
        console.print("Create a token at: https://github.com/settings/tokens")
        return 1
    
    analyzer = GitHubAnalyzer(args.token)
    
    output_path = Path(args.output)
    stats = analyzer.run_analysis(max_repos=args.max_repos, output_path=output_path)
    analyzer.print_summary(stats)
    
    return 0


if __name__ == "__main__":
    exit(main())
