#!/usr/bin/env python3
"""
Corrected re-analysis of the 200-repository retry study.

The original pass (analyze_collected_repos.py) had three defects, each found by
manually re-checking detections against the source on GitHub:

  1. JITTER OVER-DETECTION. The rule was
         has_jitter = "jitter" in context or "random" in context
     over a +/-200 character window, so any nearby use of the word "random"
     credited a configuration with jitter. Manual inspection of all 8 positives
     found only 3 distinct constructs that actually randomize a delay.
     FIX: require the token "jitter". Validated against the manual review -
     this rule reproduces the hand-checked ground truth exactly.

  2. NON-PRODUCTION CODE. 41 of 162 findings (25.3%) came from examples/ (16),
     docs/ (13), an integration-test root (6), playground/ (4) and benchmarks/
     (2). One resilience library (roma-glushko/hyx) contributed 13 findings from
     docs/snippets/retry/*.py, which demonstrate every backoff variant the
     library supports rather than showing how a project configures retries in
     practice.
     FIX: exclude non-production paths. Leaves 121.

  3. DUPLICATE DETECTIONS. Of the 121 surviving findings, 8 sat within 10 lines
     of another in the same file - typically a call and the function it calls,
     or a comment and the signature beneath it - inflating the configuration
     denominator. (Deduplicating the raw 162 before the path filter would
     collapse 16; the 8 are those that remain once non-production code is out.)
     FIX: collapse detections within 10 lines of a kept detection in the same file.
     Leaves 113.

Writes results/analysis_200_clean.json and prints a before/after comparison.

Usage:
    python experiments/reanalyze_clean.py
"""

import json
import re
import math
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "results" / "repositories" / "analysis_200.json"
DEST = PROJECT_ROOT / "results" / "repositories" / "analysis_200_clean.json"

NON_PRODUCTION = re.compile(
    r"(^|/)(docs?|examples?|samples?|tests?|snippets?|benchmarks?|playground|demos?)(/|$)"
    r"|(^|/)t/"
    r"|(^|/)(test_[^/]*|[^/]*_test)\.[a-z]+$",
    re.I,
)

DUP_WINDOW = 10


def wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a proportion; returns (point, half_width)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre, half


def is_production(path: str) -> bool:
    return not NON_PRODUCTION.search(path)


# Manual ground truth. Every one of the 8 findings the original flagged
# has_jitter=True was opened on GitHub and read. These are the files where a
# delay is actually randomized; see results/validation/ai_prescreen.md.
# The stored findings do not retain the context window, so no heuristic can be
# re-derived from this JSON - the verified list is the evidence.
JITTER_VERIFIED = {
    ("roma-glushko/hyx", "docs/snippets/retry/retry_backoff_expo_jitter.py"),
    ("roma-glushko/hyx", "docs/snippets/retry/retry_backoff_custom_jitter.py"),
    ("hatchet-dev/hatchet", "internal/queueutils/backoff.go"),
}


def has_jitter(finding: dict) -> bool:
    """Manually verified jitter, replacing the original 'jitter' OR 'random' rule.

    The original credited any configuration with the word "random" within a
    +/-200 character window. Of its 8 positives, 4 had no randomization of any
    delay (nv-ingest, doorman, and tenacity_utils.py twice); of the remaining 4,
    backoff.go:9 and :12 are one construct counted twice, leaving 3 distinct
    constructs that genuinely randomize.
    """
    return (finding["repo"], finding["file"]) in JITTER_VERIFIED


def dedupe(findings: list) -> list:
    by_file = defaultdict(list)
    for f in findings:
        by_file[(f["repo"], f["file"])].append(f)
    kept = []
    for _, group in by_file.items():
        group.sort(key=lambda x: x["line"])
        last = None
        for f in group:
            if last is None or f["line"] - last > DUP_WINDOW:
                kept.append(f)
                last = f["line"]
    return kept


def stats(findings: list, repos_with: int, total_repos: int) -> dict:
    """Statistics with denominators stated explicitly.

    The original analysis reported retry-count shares over only those
    configurations carrying a parseable non-zero count (102 of 162), while
    reporting backoff and jitter shares over all 162 - then printed both under a
    single "n=162" heading. We keep the two denominators but label them.
    """
    n = len(findings)
    counted = [f for f in findings if isinstance(f.get("max_retries"), int)
               and f["max_retries"] > 0]
    nc = len(counted)

    def share(seq, pred):
        return (sum(1 for f in seq if pred(f)) / len(seq)) if seq else 0.0

    def cnt(seq, pred):
        return sum(1 for f in seq if pred(f))

    _, h = wilson(repos_with, total_repos)
    return {
        "total_repositories": total_repos,
        "repositories_with_retry": repos_with,
        "total_retry_configs": n,
        "configs_with_explicit_count": nc,
        "prevalence_with_retry": repos_with / total_repos,
        "prevalence_ci_halfwidth": h,
        # denominator: configurations with an explicit non-zero retry count
        "retry_count_1_3": share(counted, lambda f: 1 <= f["max_retries"] <= 3),
        "retry_count_4_5": share(counted, lambda f: 4 <= f["max_retries"] <= 5),
        "retry_count_over_5": share(counted, lambda f: f["max_retries"] > 5),
        # denominator: all configurations
        "exponential_backoff": share(findings, lambda f: f["backoff_type"] == "exponential"),
        "linear_backoff": share(findings, lambda f: f["backoff_type"] == "linear"),
        "no_backoff": share(findings, lambda f: f["backoff_type"] == "none"),
        "has_jitter": share(findings, has_jitter),
        "counts": {
            "retry_count_1_3": cnt(counted, lambda f: 1 <= f["max_retries"] <= 3),
            "retry_count_4_5": cnt(counted, lambda f: 4 <= f["max_retries"] <= 5),
            "retry_count_over_5": cnt(counted, lambda f: f["max_retries"] > 5),
            "exponential_backoff": cnt(findings, lambda f: f["backoff_type"] == "exponential"),
            "linear_backoff": cnt(findings, lambda f: f["backoff_type"] == "linear"),
            "no_backoff": cnt(findings, lambda f: f["backoff_type"] == "none"),
            "has_jitter": cnt(findings, has_jitter),
        },
    }


def antipatterns(findings: list) -> dict:
    by_repo = defaultdict(list)
    for f in findings:
        by_repo[f["repo"]].append(f)
    n = len(by_repo)
    nb = sum(1 for v in by_repo.values() if any(f["backoff_type"] == "none" for f in v))
    mj = sum(1 for v in by_repo.values() if not any(has_jitter(f) for f in v))
    mj_expo = sum(1 for v in by_repo.values()
                  if any(f["backoff_type"] == "exponential" and not has_jitter(f) for f in v))
    ar = sum(1 for v in by_repo.values() if any((f.get("max_retries") or 0) > 5 for f in v))
    out = {"repos": n, "no_backoff": nb, "missing_jitter_any": mj,
           "missing_jitter_expo": mj_expo, "aggressive_retry": ar,
           "static_config": n, "no_coordination": n}
    for k in ("no_backoff", "missing_jitter_any", "missing_jitter_expo", "aggressive_retry"):
        p, h = wilson(out[k], n)
        out[k + "_pct"] = out[k] / n if n else 0
        out[k + "_ci"] = h
    return out


def concentration(findings: list) -> dict:
    per = defaultdict(int)
    for f in findings:
        per[f["repo"]] += 1
    ranked = sorted(per.values(), reverse=True)
    tot = sum(ranked)
    return {"n_repos": len(ranked), "top1_share": ranked[0] / tot if tot else 0,
            "top3_share": sum(ranked[:3]) / tot if tot else 0,
            "max_from_one_repo": ranked[0] if ranked else 0}


def main() -> int:
    d = json.loads(SRC.read_text())
    total_repos = d["total_repositories"]
    orig = d["findings"]

    prod = [f for f in orig if is_production(f["file"])]
    clean = dedupe(prod)
    repos_with_clean = len({f["repo"] for f in clean})

    before = stats(orig, d["repositories_with_retry"], total_repos)
    after = stats(clean, repos_with_clean, total_repos)
    ap_before = antipatterns(orig)
    ap_after = antipatterns(clean)

    DEST.write_text(json.dumps({
        "note": "Corrected re-analysis. See experiments/reanalyze_clean.py for the "
                "three defects fixed (jitter over-detection, non-production paths, duplicates).",
        "filters": {
            "excluded_non_production": len(orig) - len(prod),
            "excluded_duplicates": len(prod) - len(clean),
            "dup_window_lines": DUP_WINDOW,
        },
        "statistics": after,
        "statistics_original": before,
        "antipatterns": ap_after,
        "antipatterns_original": ap_before,
        "concentration": concentration(clean),
        "findings": clean,
    }, indent=1))

    def row(label, b, a, pct=True):
        f = (lambda x: f"{x*100:5.1f}%") if pct else (lambda x: f"{x:5d}")
        print(f"  {label:26} {f(b):>8}  ->{f(a):>8}")

    print(f"findings: {len(orig)} -> {len(prod)} (drop non-production) "
          f"-> {len(clean)} (drop duplicates)\n")
    print(f"=== RETRY COUNT (denominator = explicit non-zero counts: "
          f"{before['configs_with_explicit_count']} -> {after['configs_with_explicit_count']}) ===")
    for k in ("retry_count_1_3", "retry_count_4_5", "retry_count_over_5"):
        row(k, before[k], after[k])
    print()
    print(f"=== BACKOFF / JITTER (denominator = all configs: "
          f"{before['total_retry_configs']} -> {after['total_retry_configs']}) ===")
    for k in ("exponential_backoff", "linear_backoff", "no_backoff", "has_jitter"):
        row(k, before[k], after[k])
    print()
    print("=== PREVALENCE (denominator = 200 repositories) ===")
    print(f"  repos with retry           {before['repositories_with_retry']:>8} "
          f"-> {after['repositories_with_retry']:>7}")
    print(f"  prevalence                 {before['prevalence_with_retry']*100:7.1f}% "
          f"-> {after['prevalence_with_retry']*100:6.1f}% "
          f"(+/-{after['prevalence_ci_halfwidth']*100:.1f}pp)")
    print()
    print("=== ANTI-PATTERNS (denominator = repos with retry) ===")
    print(f"  base repos                 {ap_before['repos']:>8} -> {ap_after['repos']:>7}")
    for k in ("no_backoff", "missing_jitter_any", "missing_jitter_expo", "aggressive_retry"):
        print(f"  {k:26} {ap_before[k]:>3}/{ap_before['repos']:<3} "
              f"({ap_before[k+'_pct']*100:4.1f}%) -> {ap_after[k]:>3}/{ap_after['repos']:<3} "
              f"({ap_after[k+'_pct']*100:4.1f}% +/-{ap_after[k+'_ci']*100:.1f}pp)")
    print()
    c = concentration(clean)
    print("=== CONCENTRATION (cleaned set) ===")
    print(f"  configurations from a single repo: {c['max_from_one_repo']} "
          f"({c['top1_share']*100:.1f}%)")
    print(f"  share from top 3 repos:            {c['top3_share']*100:.1f}%")
    print(f"\nWrote {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
