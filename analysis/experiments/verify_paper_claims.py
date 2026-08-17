#!/usr/bin/env python3
"""
Audit every reported figure in the ICE2CPT manuscript against the result files.

Each check recomputes a number from the data in results/ and then asserts that
the manuscript actually contains that number. Nothing here is hardcoded from the
paper: the expected value is always derived, and the paper is the thing under
test. Run this before submitting, and again after any edit to the analysis.

    python analysis/experiments/verify_paper_claims.py

Exit status is 0 when every check passes, 1 otherwise.
"""

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW = PROJECT_ROOT / "results" / "repositories" / "analysis_200.json"
CLEAN = PROJECT_ROOT / "results" / "repositories" / "analysis_200_clean.json"
SIM = PROJECT_ROOT / "results" / "simulation" / "n100-reported" / "experiment_results.json"
PAPER = PROJECT_ROOT / "paper" / "retry-amplification-ice2cpt.tex"

# Mirrors reanalyze_clean.py. Kept as an independent copy on purpose: if the two
# ever drift, that is itself something this audit should surface.
NON_PRODUCTION = re.compile(
    r"(^|/)(docs?|examples?|samples?|tests?|snippets?|benchmarks?|playground|demos?)(/|$)"
    r"|(^|/)t/"
    r"|(^|/)(test_[^/]*|[^/]*_test)\.[a-z]+$",
    re.I,
)
DUP_WINDOW = 10

checks = []


def check(label, expected, present, detail=""):
    """Record one assertion: `expected` (derived from data) must be `present`."""
    checks.append((label, str(expected), bool(present), detail))


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre, half


def raf(p, n=3, d=1):
    return sum(p ** k for k in range(n + 1)) ** d


def dedupe(findings):
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


def main():
    for path in (RAW, CLEAN, SIM, PAPER):
        if not path.exists():
            sys.exit(f"missing input: {path}")

    tex = PAPER.read_text()
    # Normalise LaTeX escapes and spacing so numeric matching is not defeated by
    # "31.0\%" vs "31.0%" or by line wrapping.
    flat = re.sub(r"\s+", " ", tex).replace("\\%", "%").replace("$", "")

    raw = json.load(open(RAW))["findings"]
    clean = json.load(open(CLEAN))
    sim = json.load(open(SIM))

    # ---- Cleaning pipeline -------------------------------------------------
    nonprod = [f for f in raw if NON_PRODUCTION.search(f["file"])]
    prod = [f for f in raw if not NON_PRODUCTION.search(f["file"])]
    deduped = dedupe(prod)
    n_dups = len(prod) - len(deduped)

    check("raw detections", len(raw), f"{len(raw)} raw detections" in flat)
    check(
        f"non-production excluded ({len(nonprod)/len(raw)*100:.1f}%)",
        len(nonprod),
        f"{len(nonprod)} ({len(nonprod)/len(raw)*100:.1f}%)" in flat,
    )
    check("remaining after path filter", len(prod), f"leaving {len(prod)}" in flat)
    check("near-duplicates collapsed", n_dups, f"A further {n_dups} sat within" in flat)
    check("final configurations", len(deduped), f"{len(deduped)} configurations" in flat)

    # The JSON's own recorded filter counts must agree with a fresh recompute.
    check(
        "clean JSON records same exclusions",
        f"{len(nonprod)}/{n_dups}",
        clean["filters"]["excluded_non_production"] == len(nonprod)
        and clean["filters"]["excluded_duplicates"] == n_dups,
        "analysis_200_clean.json filters vs recompute",
    )
    check(
        "113 = 162 - 41 - 8",
        len(deduped),
        len(raw) - len(nonprod) - n_dups == len(deduped),
        "arithmetic closes",
    )

    # hyx docs/snippets contribution
    hyx = sum(
        1 for f in nonprod
        if f["repo"] == "roma-glushko/hyx" and "docs/snippets/retry" in f["file"]
    )
    check("hyx docs/snippets/retry findings", hyx, f"contributed {hyx} from" in flat)

    # ---- Detection pattern split ------------------------------------------
    pat = Counter(f.get("pattern") for f in raw)
    py = pat["python_decorator"] + pat["python_tenacity"] + pat["python_urllib3"] + pat["python_backoff"]
    generic = pat["generic_max_retries"]
    other = pat["js_retries"] + pat["go_exponential"]
    check("python-specific pattern hits", py, f"{py} matched Python-specific" in flat)
    check("generic max-retry pattern hits", generic, f"{generic} matched a language-agnostic" in flat)
    check("JS/Go pattern hits", other, f"{other} matched JavaScript- and Go-specific" in flat)
    check("pattern split sums to 162", len(raw), py + generic + other == len(raw))

    # ---- Jitter accounting -------------------------------------------------
    jit = [f for f in raw if f.get("has_jitter")]
    verified_files = {
        ("roma-glushko/hyx", "docs/snippets/retry/retry_backoff_expo_jitter.py"),
        ("roma-glushko/hyx", "docs/snippets/retry/retry_backoff_custom_jitter.py"),
        ("hatchet-dev/hatchet", "internal/queueutils/backoff.go"),
    }
    no_random = [f for f in jit if (f["repo"], f["file"]) not in verified_files]
    check("original jitter positives", len(jit), f"all {len(jit)} positives" in flat.replace("eight", "8"))
    check(
        "positives randomizing nothing",
        len(no_random),
        f"{len(no_random)} randomize no delay" in flat.replace("four", "4").replace("five", "5"),
    )
    check("distinct randomizing constructs", len(verified_files), "Three distinct constructs" in flat)

    # ---- Table II: configuration distribution ------------------------------
    st = clean["statistics"]
    c = st["counts"]
    nc = st["configs_with_explicit_count"]
    n = st["total_retry_configs"]
    rows = [
        ("retry 1-3", c["retry_count_1_3"], nc),
        ("retry 4-5", c["retry_count_4_5"], nc),
        ("retry >5", c["retry_count_over_5"], nc),
        ("exponential backoff", c["exponential_backoff"], n),
        ("linear backoff", c["linear_backoff"], n),
        ("no backoff", c["no_backoff"], n),
        ("jitter verified", c["has_jitter"], n),
    ]
    for label, k, denom in rows:
        pct = f"{k/denom*100:.1f}%"
        check(f"Table II {label}", f"{k}/{denom} = {pct}", f"{k}/{denom} & {pct}" in flat)
    check(
        "retry-count rows sum to explicit-count denominator",
        nc,
        c["retry_count_1_3"] + c["retry_count_4_5"] + c["retry_count_over_5"] == nc,
    )

    # ---- Prevalence --------------------------------------------------------
    pt, half = wilson(st["repositories_with_retry"], st["total_repositories"])
    prev = st["repositories_with_retry"] / st["total_repositories"] * 100
    check("prevalence", f"{prev:.1f}%", f"{prev:.1f}%" in flat)
    check("prevalence Wilson half-width", f"{half*100:.1f}pp", f"{half*100:.1f}%" in flat)

    # ---- Anti-patterns (per project) ---------------------------------------
    ap = clean["antipatterns"]
    for key, name in [
        ("no_backoff", "No Backoff"),
        ("missing_jitter_any", "Missing Jitter"),
        ("aggressive_retry", "Aggressive Retry"),
    ]:
        k, repos = ap[key], ap["repos"]
        pt_, half_ = wilson(k, repos)
        pct = f"{k/repos*100:.1f}%"
        check(f"anti-pattern {name}", f"{k}/{repos} = {pct}", f"({k}/{repos}, {pct}" in flat)
        check(f"anti-pattern {name} CI", f"{half_*100:.1f}pp", f"{half_*100:.1f}pp" in flat)
    k, repos = ap["missing_jitter_expo"], ap["repos"]
    check(
        "Missing Jitter (narrow reading)",
        f"{k}/{repos} = {k/repos*100:.1f}%",
        f"{k}/{repos} ({k/repos*100:.1f}%)" in flat,
    )

    # ---- Concentration -----------------------------------------------------
    con = clean["concentration"]
    check(
        "top-1 project configurations",
        con["max_from_one_repo"],
        f"one project supplies {con['max_from_one_repo']} of" in flat
        or f"supplying {con['max_from_one_repo']} of" in flat,
    )
    check(
        "top-3 share",
        f"{con['top3_share']*100:.0f}%",
        f"top three {con['top3_share']*100:.0f}%" in flat
        or f"top three supply {con['top3_share']*100:.0f}%" in flat,
    )

    # ---- Analytical RAF ----------------------------------------------------
    check("RAF p=0.5 n=3", f"{raf(0.5):.3f}", f"{raf(0.5):.3f}" in flat)
    check("RAF p=0.5 d=3", f"{raf(0.5, d=3):.2f}", f"{raf(0.5, d=3):.2f}" in flat)
    check("RAF p=0.3 n=3", f"{raf(0.3):.3f}", f"({raf(0.3):.3f})" in flat)
    check("RAF p=0.3 d=3", f"{raf(0.3, d=3):.2f}", f"{raf(0.3, d=3):.2f}" in flat)
    # Table IV must follow from the scenarios the experiment actually runs, not
    # from hand-typed values. Read the parameters back out of the source so that
    # editing a scenario and forgetting the table is caught here.
    scen = (PROJECT_ROOT / "analysis" / "src" / "simulation" / "scenarios.py").read_text()
    runner = (PROJECT_ROOT / "analysis" / "experiments" / "run_simulation.py").read_text()

    # S1: one tier, p from the runner's explicit argument.
    s1_p = float(re.search(r"s1_single_service_failure\(\s*failure_probability=([\d.]+)", runner).group(1))
    check("S1 p from run_simulation.py", s1_p, s1_p == 0.5)
    check("Table IV S1", f"{raf(s1_p):.2f}", f"{int(s1_p*100)}% at tier 3 & {raf(s1_p):.2f}" in flat)

    # S2: custom injector ramps p over the window; affected tiers give the depth.
    lo_s2, span = (float(x) for x in re.search(
        r"return ([\d.]+) \+ ([\d.]+) \* progress", scen).groups())
    hi_s2 = lo_s2 + span
    d_s2 = len(re.search(r"affected_tiers=\[([\d, ]+)\],\s*# Deeper tiers", scen).group(1).split(","))
    check("S2 ramp from scenarios.py", f"{lo_s2}->{hi_s2} over {d_s2} tiers", d_s2 == 2)
    check(
        "Table IV S2",
        f"{raf(lo_s2, d=d_s2):.2f}--{raf(hi_s2, d=d_s2):.2f}",
        f"{int(lo_s2*100)}%\\rightarrow{int(hi_s2*100)}% at tiers 4--5 & "
        f"{raf(lo_s2, d=d_s2):.2f}--{raf(hi_s2, d=d_s2):.2f}" in flat,
    )

    # S3: p from the runner, depth from the scenario's affected tiers.
    s3_p = float(re.search(r"s3_correlated_failures\(\s*failure_probability=([\d.]+)", runner).group(1))
    d_s3 = len(re.search(r"affected_tiers=\[([\d, ]+)\],\s*# Multiple tiers", scen).group(1).split(","))
    check("S3 p from run_simulation.py", s3_p, s3_p == 0.6)
    check(
        "Table IV S3",
        f"{raf(s3_p, d=d_s3):.2f}",
        f"{int(s3_p*100)}% at tiers 3--5 & {raf(s3_p, d=d_s3):.2f}" in flat,
    )
    check(
        "Evaluation text cites the S3 bound",
        f"{raf(s3_p, d=d_s3):.2f}",
        f"{raf(s3_p, d=d_s3):.2f}$\\times$ for S3" in tex,
    )

    # ---- Simulation: Tables V and VI ---------------------------------------
    for strat in ("NR", "SR", "CB", "ARB"):
        for sc in ("S1", "S2", "S3"):
            r = sim[strat][sc]
            check(
                f"Table V {strat} {sc} success",
                f"{r['success_rate_mean']*100:.1f}%",
                f"{r['success_rate_mean']*100:.1f}%" in flat,
            )
            check(
                f"Table VI {strat} {sc} RAF",
                f"{r['raf_mean']:.2f}",
                f"{r['raf_mean']:.2f}" in flat,
            )
            check(f"{strat} {sc} n=100", 100, r["num_trials"] == 100)

    # ---- Headline relative claim ------------------------------------------
    nr3 = sim["NR"]["S3"]["success_rate_mean"]
    sr3 = sim["SR"]["S3"]["success_rate_mean"]
    rel = (nr3 - sr3) / nr3 * 100
    check(
        "SR vs NR relative degradation under S3",
        f"{rel:.0f}%",
        f"relative degradation of {rel:.0f}%" in flat,
    )

    # ---- Precision sample --------------------------------------------------
    sample = (PROJECT_ROOT / "results" / "validation" / "precision_sample.md").read_text()
    verdicts = re.findall(r"^- verdict: ([yn?])$", sample, re.M)
    genuine = verdicts.count("y")
    unmarked = verdicts.count("?")
    check("precision sample size", 30, len(verdicts) == 30)
    check("precision sample fully adjudicated", "0 unmarked", unmarked == 0,
          f"{unmarked} still '?'" if unmarked else "")
    if verdicts and not unmarked:
        pct = f"{genuine/len(verdicts)*100:.1f}%"
        check("precision", f"{genuine}/{len(verdicts)} = {pct}", f"{pct}" in flat)

    # ---- Built artifact freshness -----------------------------------------
    # The checks above read the .tex. A stale PDF built before the last source
    # edit would pass every one of them and still be the wrong thing to submit.
    pdf = PAPER.with_suffix(".pdf")
    check(
        "PDF newer than .tex",
        "rebuild needed" if not pdf.exists() or pdf.stat().st_mtime < PAPER.stat().st_mtime else "fresh",
        pdf.exists() and pdf.stat().st_mtime >= PAPER.stat().st_mtime,
        "run: cd paper && make",
    )

    # ---- Report ------------------------------------------------------------
    width = max(len(c[0]) for c in checks) + 2
    failed = 0
    for label, expected, ok, detail in checks:
        if not ok:
            failed += 1
        mark = "ok  " if ok else "FAIL"
        line = f"  {mark}  {label:<{width}} {expected}"
        if detail:
            line += f"   [{detail}]"
        print(line)

    print(f"\n{len(checks) - failed}/{len(checks)} checks passed.")
    if failed:
        print(
            f"\n{failed} claim(s) in the manuscript do not match the data. Either the\n"
            "paper needs editing or the analysis changed and the paper was not updated."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
