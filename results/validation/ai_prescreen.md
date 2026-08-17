# AI pre-screen of the precision sample

**This is not the validation.** It is a machine-assisted first pass over the same
30 seeded items in `precision_sample.md`, produced by fetching each file from
GitHub at HEAD and reading the code around the detection. The authors must
confirm or override each verdict before any number derived from it appears in
the paper, and the paper must describe what actually happened.

Method: `curl` of `raw.githubusercontent.com/{repo}/HEAD/{file}`, then locate the
recorded evidence string (line numbers have drifted since the January analysis,
so the evidence string rather than the line number was used to locate the code).

## Per-item assessment

| # | Repo | Assessment | Note |
|---|------|-----------|------|
| 1 | hatchet-dev/hatchet | genuine | `retries: 3` in a Hatchet task config |
| 2 | nvidia-cosmos/cosmos-curate | genuine | `@tenacity.retry(stop_after_attempt(3), wait_exponential(...))` |
| 3 | lzjever/routilux | genuine | `ErrorHandler(strategy=RETRY, max_retries=4, retry_delay=0.3)` |
| 4 | apidoorman/doorman | **questionable** | `env_max_retries = 0` is a local initializer before an env lookup; extracted `jitter=True` is wrong |
| 5 | modal-labs/modal-examples | genuine | `modal.Retries(max_retries=3, backoff_coefficient=2.0)` |
| 6 | AnubisLMS/Anubis | genuine | `@retry(tries=3)` |
| 7 | lzjever/routilux | genuine | `RetryRouter(max_retries=3)` |
| 8 | open-edge-platform | genuine | parameter default in `upload_single_video_with_retry` |
| 9 | PrimeIntellect-ai/prime | genuine | `@retry(stop_after_attempt(5), wait_exponential(...))` |
| 10 | VOLTTRON/volttron | genuine | parameter default `max_retries=12` |
| 11 | lzjever/routilux | genuine | `ErrorHandler(strategy=RETRY, max_retries=4)` |
| 12 | roma-glushko/hyx | genuine | but `backoff=expo(...)` was recorded as **linear**; it is exponential. Also a docs snippet |
| 13 | roma-glushko/hyx | genuine | `@retry(backoff=0.5)` constant. Docs snippet |
| 14 | zd87pl/ai-crypto-trader | genuine | `connect_redis(max_retries=15, retry_delay=2)` |
| 15 | celery/celery | genuine | `HTTPAdapter(max_retries=3)` |
| 16 | open-edge-platform | genuine | `connect_opcua_client(..., max_retries=10)` |
| 17 | zd87pl/ai-crypto-trader | genuine | `connect_redis(max_retries=10, retry_delay=5)` with retry loop |
| 18 | aws-samples/observability | genuine | `Retry(total=2, status_forcelist=[...])` |
| 19 | AgnetLabs/Laddr | genuine | `max_retries = 10` + `for attempt in range(max_retries)` |
| 20 | celery/celery | genuine | `@shared_task(max_retries=1)` — but in `t/integration/tasks.py`, a **test fixture** |
| 21 | zd87pl/ai-crypto-trader | genuine | `connect_redis(max_retries=5, retry_delay=5)` |
| 22 | hashview/hashview | genuine | `Retry(total=100, backoff_factor=1)` |
| 23 | zd87pl/ai-crypto-trader | genuine | `connect_redis(max_retries=15, retry_delay=2)` |
| 24 | modal-labs/modal-client | **unresolvable** | `modal/volume.py` returns 404 at HEAD; file moved since January |
| 25 | OpenBMB/IoA | genuine | `litellm.completion(max_retries=5, num_retries=5)` in a retry loop |
| 26 | allenai/genesys | genuine | `search_arxiv(..., max_retries=3, retry_delay=...)` |
| 27 | open-edge-platform | genuine | `_verify_connection(max_retries=10)` |
| 28 | adidas/lakehouse-engine | genuine | `@retry(stop_after_attempt(5), wait_exponential(multiplier=30))` |
| 29 | OpenBMB/IoA | genuine | `@retry(stop_after_attempt(5), retry_if_exception_type(RequestError))` |
| 30 | hatchet-dev/hatchet | genuine | `tenacity.retry(wait=config.wait(), stop=stop_after_attempt(...))` |

**Pre-screen tally:** 28 genuine of 29 resolvable = **96.6%**, one unresolvable.
Counting item 4 as a false positive gives 27/29 = 93.1%.

## Separate finding: jitter is over-counted

All 8 `has_jitter=True` findings in the full dataset were inspected.

| Repo / file | Real jitter? |
|---|---|
| roma-glushko/hyx `retry_backoff_expo_jitter.py` | **yes** — `jitter=jitters.full` (docs snippet) |
| roma-glushko/hyx `retry_backoff_custom_jitter.py` | **yes** — `jitter=partial(randomixin)`, `random.uniform` (docs snippet) |
| hatchet-dev/hatchet `backoff.go:9` | **yes** — `math/rand`, jitter in the implementation |
| hatchet-dev/hatchet `backoff.go:12` | yes, but **duplicate of the line above**, same function |
| hatchet-dev/hatchet `tenacity_utils.py:19` | **no visible jitter** — `wait=config.wait()` indirection |
| hatchet-dev/hatchet `tenacity_utils.py:24` | same, and **duplicate of line 19** |
| NVIDIA/nv-ingest `post_build_triggers.py:7` | **no** — `MAX_RETRIES = 5`, no randomness anywhere nearby |
| apidoorman/doorman `gateway_service.py:2281` | **no** — `env_max_retries = 0`, no randomness |

Distinct constructs genuinely implementing jitter: **3**, i.e. roughly **1.9%** of 162,
not 4.9%. Two of the three are documentation snippets in a resilience library.

## Dataset-quality issues found while checking

1. **Non-production paths: 35/162 (21.6%)** are under `docs/`, `examples/`,
   `tests/`, `snippets/`, `benchmarks/`, `playground/`. `roma-glushko/hyx`
   contributes 14, nearly all `docs/snippets/retry/*.py` — a resilience library's
   documentation demonstrating every backoff variant it supports.
2. **Duplicate detections:** 17 detections sit within 10 lines of another in the
   same file; 36 files carry more than one. Examples: `ntp.py` lines 20 and 22
   (a call and the function it calls), `backoff.go` lines 9 and 12.
3. **Repo concentration:** `zd87pl/ai-crypto-trader` alone supplies 23 of 162
   configurations (14%); the top three repos supply 61 (38%). The 162 are not
   independent observations, so per-configuration confidence intervals computed
   as if they were will be too narrow.
4. **Field extraction errors on otherwise-genuine detections:** item 12's
   `expo(...)` recorded as linear; item 4's `jitter=True` with no randomness present.

## Correction to this record (applied after the exclusion rule was finalized)

Items 1 and 2 above were written against an earlier, narrower non-production
path rule and are superseded by what `reanalyze_clean.py` actually computes.
Recomputed from `analysis_200.json` with the shipped `NON_PRODUCTION` regex:

- Non-production paths are **41/162 (25.3%)**, not 35 (21.6%). The rule was later
  broadened to add `playground/`, `samples/`, `demos/` and bare integration-test
  roots (`t/`), which catches 10 further detections (celery `t/integration/tasks.py`
  x6, routilux `playground/...` x4). Breakdown: `examples/` 16, `docs/` 13,
  `t/` 6, `playground/` 4, `benchmarks/` 2.
- `roma-glushko/hyx` contributes **13**, not 14 — all of them under
  `docs/snippets/retry/`.
- The **17** duplicate detections in item 2 are the count over the raw 162 before
  the path filter (recomputing gives 16). The pipeline dedupes *after* excluding
  non-production code, where **8** collapse. 162 - 41 - 8 = 113, which is the
  figure the paper reports.

The jitter table above is unaffected and remains the ground truth for
`JITTER_VERIFIED`. Note for the record that of the 8 positives, **4** randomize
no delay (nv-ingest, doorman, and `tenacity_utils.py` twice), not 5.

## Not done

The false-negative half (30 repositories with no detection) has **not** been
checked. It requires searching each repository for retry logic the regex rules
would have missed, which is materially harder than confirming a known line and
was not attempted here. The 6.7% figure in the paper remains unsupported.
