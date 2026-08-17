#!/usr/bin/env python3
"""
Detection validation sampler and scorer.

Produces the manual-validation evidence behind the precision and false-negative
rates reported in the paper's "Validation and Limits of Static Analysis" section.

Two phases:

  1. GENERATE  Draw a seeded random sample of detected retry configurations
               (precision check) and a seeded sample of repositories where
               nothing was detected (false-negative check). Writes two markdown
               checklists with a GitHub link for every item.

  2. SCORE     Read the filled-in checklists back and compute precision and the
               estimated false-negative rate, writing a JSON artifact that can
               be cited and re-checked.

The seed is fixed so the sample is reproducible: anyone re-running this with the
same seed and the same analysis_200.json gets the identical 30 items.

Usage:
    # Phase 1 - draw the samples
    python experiments/validate_detection.py generate

    # ... hand-check each item, replacing "verdict: ?" with y or n ...

    # Phase 2 - score the completed checklists
    python experiments/validate_detection.py score
"""

import json
import random
import argparse
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = PROJECT_ROOT / "results" / "repositories" / "analysis_200.json"
OUTDIR = PROJECT_ROOT / "results" / "validation"

SEED = 20260814
SAMPLE_SIZE = 30


def gh_file_url(repo: str, path: str, line: int) -> str:
    """Permalink to a specific line, for one-click verification."""
    return f"https://github.com/{repo}/blob/HEAD/{path}#L{line}"


def gh_search_url(repo: str) -> str:
    """Scoped code search for retry-ish terms inside one repository."""
    q = f"repo:{repo} retry OR retries OR backoff OR reconnect"
    return "https://github.com/search?type=code&q=" + q.replace(" ", "+").replace(":", "%3A")


def generate() -> None:
    data = json.loads(ANALYSIS.read_text())
    findings = data["findings"]
    repos = data["repositories"]
    no_detect = [r for r in repos if not r.get("has_retry")]

    rng = random.Random(SEED)
    prec_sample = rng.sample(findings, min(SAMPLE_SIZE, len(findings)))
    recall_sample = rng.sample(no_detect, min(SAMPLE_SIZE, len(no_detect)))

    OUTDIR.mkdir(parents=True, exist_ok=True)

    # ---- precision checklist -------------------------------------------------
    lines = [
        "# Precision check",
        "",
        f"Seeded random sample of {len(prec_sample)} detected retry configurations "
        f"drawn from {len(findings)} total findings (seed {SEED}).",
        "",
        "For each item: open the link, read the surrounding code, and decide whether",
        "this is genuinely a retry configuration. Replace `verdict: ?` with:",
        "",
        "  - `y` - genuine retry configuration",
        "  - `n` - false positive (e.g. a variable that merely contains 'retry')",
        "",
        "Also sanity-check the extracted fields; note anything wrong in the `notes` line.",
        "",
        "---",
        "",
    ]
    for i, f in enumerate(prec_sample, 1):
        lines += [
            f"## {i}. `{f['repo']}`",
            "",
            f"- url: {gh_file_url(f['repo'], f['file'], f['line'])}",
            f"- file: `{f['file']}:{f['line']}`",
            f"- pattern: `{f['pattern']}`",
            f"- extracted: max_retries=`{f['max_retries']}` "
            f"backoff=`{f['backoff_type']}` jitter=`{f['has_jitter']}`",
            f"- evidence: `{f['evidence']}`",
            "- verdict: ?",
            "- notes:",
            "",
        ]
    (OUTDIR / "precision_sample.md").write_text("\n".join(lines))

    # ---- false-negative checklist -------------------------------------------
    lines = [
        "# False-negative check",
        "",
        f"Seeded random sample of {len(recall_sample)} repositories where the analyzer "
        f"detected no retry logic, drawn from {len(no_detect)} such repositories (seed {SEED}).",
        "",
        "For each: search the repository for retry logic the regex rules would have missed",
        "(hand-rolled loops, framework YAML, dynamic config). Replace `verdict: ?` with:",
        "",
        "  - `y` - retry logic IS present and we missed it (a false negative)",
        "  - `n` - no retry logic found, detector was correct",
        "",
        "---",
        "",
    ]
    for i, r in enumerate(recall_sample, 1):
        lines += [
            f"## {i}. `{r['name']}`",
            "",
            f"- repo: https://github.com/{r['name']}",
            f"- search: {gh_search_url(r['name'])}",
            f"- language: {r.get('language')}",
            "- verdict: ?",
            "- notes:",
            "",
        ]
    (OUTDIR / "recall_sample.md").write_text("\n".join(lines))

    print(f"Wrote {OUTDIR / 'precision_sample.md'}  ({len(prec_sample)} items)")
    print(f"Wrote {OUTDIR / 'recall_sample.md'}     ({len(recall_sample)} items)")
    print(f"\nSeed {SEED}. Fill in each 'verdict: ?' then run:")
    print("  python experiments/validate_detection.py score")


def parse_verdicts(path: Path) -> list:
    if not path.exists():
        return []
    return re.findall(r"^- verdict:\s*(\S+)\s*$", path.read_text(), re.MULTILINE)


def score() -> None:
    prec = parse_verdicts(OUTDIR / "precision_sample.md")
    rec = parse_verdicts(OUTDIR / "recall_sample.md")

    def tally(verdicts, label):
        done = [v.lower() for v in verdicts if v.lower() in ("y", "n")]
        pending = len(verdicts) - len(done)
        if pending:
            print(f"  {label}: {pending} of {len(verdicts)} still unmarked ('?')")
        return done, pending

    print("Scoring...\n")
    pd, p_pending = tally(prec, "precision")
    rd, r_pending = tally(rec, "false-negative")

    out = {"seed": SEED, "sample_size": SAMPLE_SIZE}

    if pd:
        yes = pd.count("y")
        out["precision"] = {
            "checked": len(pd), "genuine": yes, "false_positives": len(pd) - yes,
            "precision": round(yes / len(pd), 4),
        }
        print(f"\nPrecision: {yes}/{len(pd)} genuine = {yes/len(pd)*100:.1f}%")

    if rd:
        yes = rd.count("y")
        out["false_negative"] = {
            "checked": len(rd), "missed_retry_logic": yes,
            "false_negative_rate": round(yes / len(rd), 4),
        }
        print(f"False-negative rate: {yes}/{len(rd)} missed = {yes/len(rd)*100:.1f}%")

    if not pd and not rd:
        print("Nothing marked yet - fill in the 'verdict: ?' lines first.")
        return

    if p_pending or r_pending:
        print("\nWARNING: results are partial - some items are still unmarked.")

    dest = OUTDIR / "validation_results.json"
    dest.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {dest}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["generate", "score"])
    args = ap.parse_args()

    if not ANALYSIS.exists():
        print(f"Missing {ANALYSIS}")
        return 1

    generate() if args.phase == "generate" else score()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
