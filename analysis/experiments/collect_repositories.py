#!/usr/bin/env python3
"""
Repository Collection Script

This script collects the list of GitHub repositories matching the paper's criteria:
- Primary language: Java, Go, Python, or JavaScript/TypeScript
- Contains "microservice" or "distributed" in description or README
- More than 50 stars (quality filter)
- Active development (commits within past 12 months)

Usage:
    # Set your GitHub token
    export GITHUB_TOKEN="your_token_here"
    
    # Run collection
    python experiments/collect_repositories.py --output results/repository_list.json
    
    # Or with token as argument
    python experiments/collect_repositories.py --token YOUR_TOKEN --max-repos 1000

To get a GitHub token:
    1. Go to https://github.com/settings/tokens
    2. Generate new token (classic)
    3. Select 'public_repo' scope
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Generator, Optional

try:
    from github import Github, RateLimitExceededException
    from github.Repository import Repository
    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False
    print("PyGithub not installed. Install with: pip install PyGithub")

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table

console = Console()


@dataclass
class RepoInfo:
    """Information about a repository."""
    full_name: str
    url: str
    description: str
    language: str
    stars: int
    forks: int
    created_at: str
    updated_at: str
    pushed_at: str
    topics: list
    has_readme_keyword: bool = False
    search_query: str = ""
    
    def to_dict(self):
        return asdict(self)


class RepositoryCollector:
    """Collects repositories matching research criteria."""
    
    LANGUAGES = ["Python", "Go", "Java", "JavaScript", "TypeScript"]
    KEYWORDS = ["microservice", "microservices", "distributed", "distributed-systems"]
    
    def __init__(self, token: str):
        if not HAS_GITHUB:
            raise ImportError("PyGithub required")
        
        self.github = Github(token, per_page=100)
        self.collected: dict[str, RepoInfo] = {}  # Use dict to dedupe by full_name
        
    def search_repositories(
        self,
        max_repos: int = 2500,
        min_stars: int = 50,
    ) -> Generator[RepoInfo, None, None]:
        """
        Search GitHub for repositories matching criteria.
        
        Yields RepoInfo objects for each matching repository.
        """
        # Calculate date filter (active in past 12 months)
        one_year_ago = datetime.now() - timedelta(days=365)
        date_str = one_year_ago.strftime("%Y-%m-%d")
        
        seen_repos = set()
        total_found = 0
        
        for language in self.LANGUAGES:
            for keyword in self.KEYWORDS:
                if total_found >= max_repos:
                    return
                
                # Search in repository name/description
                query = f'"{keyword}" language:{language} stars:>={min_stars} pushed:>={date_str}'
                
                console.print(f"[dim]Searching: {query}[/dim]")
                
                try:
                    results = self.github.search_repositories(
                        query=query,
                        sort="stars",
                        order="desc"
                    )
                    
                    for repo in results:
                        if total_found >= max_repos:
                            return
                        
                        if repo.full_name in seen_repos:
                            continue
                        
                        seen_repos.add(repo.full_name)
                        
                        info = RepoInfo(
                            full_name=repo.full_name,
                            url=repo.html_url,
                            description=repo.description or "",
                            language=repo.language or "Unknown",
                            stars=repo.stargazers_count,
                            forks=repo.forks_count,
                            created_at=repo.created_at.isoformat() if repo.created_at else "",
                            updated_at=repo.updated_at.isoformat() if repo.updated_at else "",
                            pushed_at=repo.pushed_at.isoformat() if repo.pushed_at else "",
                            topics=repo.topics if hasattr(repo, 'topics') else [],
                            search_query=query,
                        )
                        
                        total_found += 1
                        yield info
                        
                except RateLimitExceededException:
                    console.print("[yellow]Rate limit hit. Waiting 60 seconds...[/yellow]")
                    time.sleep(60)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
                    time.sleep(5)
    
    def collect_all(self, max_repos: int = 2500, min_stars: int = 50) -> list[RepoInfo]:
        """Collect all matching repositories."""
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed} repos"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            
            task = progress.add_task("[cyan]Collecting repositories...", total=None)
            
            for info in self.search_repositories(max_repos=max_repos, min_stars=min_stars):
                self.collected[info.full_name] = info
                progress.update(task, completed=len(self.collected), 
                              description=f"[cyan]{info.full_name[:40]}...")
        
        return list(self.collected.values())


def save_results(repos: list[RepoInfo], output_path: Path):
    """Save collected repositories to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "collection_date": datetime.now().isoformat(),
        "total_repositories": len(repos),
        "criteria": {
            "languages": RepositoryCollector.LANGUAGES,
            "keywords": RepositoryCollector.KEYWORDS,
            "min_stars": 50,
            "active_within_days": 365,
        },
        "repositories": [r.to_dict() for r in repos],
    }
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    # Also save a simple CSV for easy viewing
    csv_path = output_path.with_suffix(".csv")
    with open(csv_path, "w") as f:
        f.write("name,url,language,stars,description\n")
        for r in repos:
            desc = r.description.replace('"', "'")[:100] if r.description else ""
            f.write(f'"{r.full_name}","{r.url}","{r.language}",{r.stars},"{desc}"\n')
    
    console.print(f"\n[green]Saved {len(repos)} repositories to:[/green]")
    console.print(f"  • {output_path}")
    console.print(f"  • {csv_path}")


def print_summary(repos: list[RepoInfo]):
    """Print summary statistics."""
    
    console.print("\n[bold]Collection Summary[/bold]")
    console.print("=" * 50)
    
    # By language
    by_lang = {}
    for r in repos:
        by_lang[r.language] = by_lang.get(r.language, 0) + 1
    
    table = Table(title="Repositories by Language")
    table.add_column("Language")
    table.add_column("Count")
    table.add_column("Percentage")
    
    for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
        table.add_row(lang, str(count), f"{count/len(repos)*100:.1f}%")
    
    console.print(table)
    
    # Star distribution
    console.print("\n[bold]Star Distribution:[/bold]")
    star_ranges = [(50, 100), (100, 500), (500, 1000), (1000, 5000), (5000, float('inf'))]
    for low, high in star_ranges:
        count = sum(1 for r in repos if low <= r.stars < high)
        high_str = str(int(high)) if high != float('inf') else "+"
        console.print(f"  {low}-{high_str} stars: {count} repos")
    
    # Top repositories
    console.print("\n[bold]Top 10 by Stars:[/bold]")
    for r in sorted(repos, key=lambda x: -x.stars)[:10]:
        console.print(f"  ⭐ {r.stars:,} - {r.full_name} ({r.language})")


def main():
    parser = argparse.ArgumentParser(description="Collect GitHub repositories for analysis")
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub API token (or set GITHUB_TOKEN env var)"
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=2500,
        help="Maximum repositories to collect (default: 2500)"
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=50,
        help="Minimum star count (default: 50)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="results/repositories/repository_list.json",
        help="Output file path"
    )
    
    args = parser.parse_args()
    
    if not args.token:
        console.print("[bold red]GitHub token required![/bold red]")
        console.print("\nTo get a token:")
        console.print("  1. Go to https://github.com/settings/tokens")
        console.print("  2. Click 'Generate new token (classic)'")
        console.print("  3. Select 'public_repo' scope")
        console.print("  4. Run: export GITHUB_TOKEN='your_token'")
        console.print("     Or: python collect_repositories.py --token YOUR_TOKEN")
        return 1
    
    console.print("\n[bold blue]GitHub Repository Collector[/bold blue]")
    console.print(f"Collecting up to {args.max_repos} repositories with ≥{args.min_stars} stars\n")
    
    collector = RepositoryCollector(args.token)
    repos = collector.collect_all(max_repos=args.max_repos, min_stars=args.min_stars)
    
    print_summary(repos)
    
    output_path = Path(args.output)
    save_results(repos, output_path)
    
    console.print(f"\n[bold green]✓ Collected {len(repos)} repositories[/bold green]")
    console.print("\nNext step: Run analysis with:")
    console.print(f"  python experiments/analyze_collected_repos.py --input {output_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
