# False-negative check

Seeded random sample of 30 repositories where the analyzer detected no retry logic, drawn from 177 such repositories (seed 20260814).

For each: search the repository for retry logic the regex rules would have missed
(hand-rolled loops, framework YAML, dynamic config). Replace `verdict: ?` with:

  - `y` - retry logic IS present and we missed it (a false negative)
  - `n` - no retry logic found, detector was correct

---

## Provenance and criterion

**These verdicts were produced by a tool-assisted pass, not by an unaided human
read. Reviewed and signed off by the corresponding author (R. Mehan), 16 August
2026; the authors take responsibility for them.**
Method: each repository's HEAD tarball was downloaded from `codeload.github.com`,
extracted, and every source file (`.py .go .java .js .ts .tsx .yaml .yml .toml
.cfg .ini`, excluding `node_modules/ vendor/ third_party/ dist/ build/`) was
searched for `retry retries retrying backoff back_off reconnect max_attempts
num_retries retry_count retry_delay tenacity max_retries RetryError`, plus
hand-rolled loop shapes (`for <attempt> in range(...)`, `while <attempt> ...`).
Matches were split into production and non-production paths using the same
filter as `reanalyze_clean.py`. Every verdict below cites file and line.

**Do not use GitHub's REST code-search API for this.** It was tried first and
returned `total_count: 0` for all 30 repositories, including ones that plainly
contain retry code — `repo:`-qualified queries silently return zero on that
endpoint while `org:`-qualified ones work. It would have produced a clean and
entirely false "no false negatives" result.

**Criterion applied.** A false negative (`y`) is production code that reattempts
a failed operation *against a dependency* — a network call, an RPC, a
connection, a queue broker. Excluded (`n`): CI job-retry keys, hardware
spin-waits, retries of purely local computation, unimplemented TODOs, and
matches appearing only in comments. Two borderline cases (5 and 29) are recorded
with the reasoning that put them on the `n` side, so a reader who draws the line
differently can move them.

**Tally: 10 of 30 repositories with no detection do in fact contain retry
logic — a repository-level false-negative rate of 33.3%** (Wilson 95% CI
19.2%--51.2%). Two of the ten (18, 25) were missed on patterns the detector
already implements, rather than on exotic ones; the rest are hand-rolled loops
and vendored helpers. See the implications note at the end of this file.

---

## 1. `MLOPTPSU/FedTorch`

- repo: https://github.com/MLOPTPSU/FedTorch
- search: https://github.com/search?type=code&q=repo%3AMLOPTPSU/FedTorch+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 93 source files, no match for retry/retries/backoff/reconnect/max_attempts/tenacity anywhere. Federated-learning research code; failure handling is not present at all.

## 2. `taogeYT/fast-grpc`

- repo: https://github.com/taogeYT/fast-grpc
- search: https://github.com/search?type=code&q=repo%3AtaogeYT/fast-grpc+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 30 source files, no match. A gRPC service framework, but it exposes no retry facility of its own.

## 3. `keijack/python-eureka-client`

- repo: https://github.com/keijack/python-eureka-client
- search: https://github.com/search?type=code&q=repo%3Akeijack/python-eureka-client+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `py_eureka_client/__aws_info_loader.py:44` — `for i in range(_CONNECTIVITY_TEST_TIMES)` wrapping `socket.connect()` to the AWS metadata service, with `time.sleep(1)` between attempts. A hand-rolled bounded retry with fixed backoff on a network call; no library idiom, so no rule fired.

## 4. `ydf0509/funboost`

- repo: https://github.com/ydf0509/funboost
- search: https://github.com/search?type=code&q=repo%3Aydf0509/funboost+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `funboost/core/broker_kind__exclusive_config_default_define.py:74` carries `retries=0, retry_delay=0` defaults; `funboost/funweb/flask_bps/script_deploy.py:1238-1243` implements a `restart_retry_count` against `max_retry`; `funboost/contrib/funspider/http.py:110,148` are hand-rolled attempt loops. A task-queue framework whose whole point includes retry.

## 5. `jr-robotics/robo-gym`

- repo: https://github.com/jr-robotics/robo-gym
- search: https://github.com/search?type=code&q=repo%3Ajr-robotics/robo-gym+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: Only match is `.gitlab-ci.yml:33` `retry:`, a GitLab CI job-retry key. Build-infrastructure retry, not an application retry policy against a service dependency, so out of scope by the criterion above.

## 6. `Pathwit/file2md`

- repo: https://github.com/Pathwit/file2md
- search: https://github.com/search?type=code&q=repo%3APathwit/file2md+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `app/utils.py:279` defines `async def retry_async(func, max_retries=3, delay=1.0, backoff_factor=2.0, exceptions=(...))` with `for attempt in range(max_retries + 1)`; `app/vision.py:143` runs `for attempt in range(config.VISION_MAX_RETRIES)`. A hand-rolled exponential-backoff helper — exactly the shape the regexes cannot see.

## 7. `internetarchive/brozzler`

- repo: https://github.com/internetarchive/brozzler
- search: https://github.com/search?type=code&q=repo%3Ainternetarchive/brozzler+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `brozzler/worker.py:695` computes `retry_delay = min(135, 60 * (1.5 ** (page.failed_attempts or 0)))` — hand-rolled exponential backoff. `brozzler/ydl.py:340-397` runs `while attempt < max_attempts` with 'Attempt %s failed. Retrying in %s seconds'.

## 8. `armadaplatform/armada`

- repo: https://github.com/armadaplatform/armada
- search: https://github.com/search?type=code&q=repo%3Aarmadaplatform/armada+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `armada_command/armada_utils.py:101` defines `execute_local_command(command, stream_output=False, retries=0)` with `for i in range(retries + 1)`, called with `retries=3` from `command_build.py:97` and `command_push.py:75`. A separate `@retry(num_retries=...)` decorator is defined and used at `armada_agent.py:80,109`, including `num_retries=float('inf')`.

## 9. `Agentfy-io/Agentfy`

- repo: https://github.com/Agentfy-io/Agentfy
- search: https://github.com/search?type=code&q=repo%3AAgentfy-io/Agentfy+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `common/utils/helpers.py:58` defines `def retry(func, max_retries=3, retry_delay=1, ...)` documented as 'Retry a function call with exponential backoff', with the delay compounding at line 64.

## 10. `mcgoon/MetaAurora`

- repo: https://github.com/mcgoon/MetaAurora
- search: https://github.com/search?type=code&q=repo%3Amcgoon/MetaAurora+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: Only 2 source files in the repository; no match.

## 11. `community-of-python/microbootstrap`

- repo: https://github.com/community-of-python/microbootstrap
- search: https://github.com/search?type=code&q=repo%3Acommunity-of-python/microbootstrap+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 64 source files, no production match. A service-bootstrap library; it configures logging, metrics and tracing but ships no retry facility.

## 12. `dask/dask-image`

- repo: https://github.com/dask/dask-image
- search: https://github.com/search?type=code&q=repo%3Adask/dask-image+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 76 source files, no match. Image-processing library, no network calls to retry.

## 13. `freelawproject/doctor`

- repo: https://github.com/freelawproject/doctor
- search: https://github.com/search?type=code&q=repo%3Afreelawproject/doctor+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 20 source files, no match.

## 14. `aws-containers/eks-app-mesh-polyglot-demo`

- repo: https://github.com/aws-containers/eks-app-mesh-polyglot-demo
- search: https://github.com/search?type=code&q=repo%3Aaws-containers/eks-app-mesh-polyglot-demo+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 60 source files, no match. The demo delegates resilience to the App Mesh data plane rather than to application code — consistent with the paper's argument that mesh-level policy displaces in-code retry.

## 15. `umermansoor/microservices`

- repo: https://github.com/umermansoor/microservices
- search: https://github.com/search?type=code&q=repo%3Aumermansoor/microservices+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 10 source files, no match. A teaching example of a microservice split.

## 16. `cheshire-cat-ai/core`

- repo: https://github.com/cheshire-cat-ai/core
- search: https://github.com/search?type=code&q=repo%3Acheshire-cat-ai/core+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: Two comments reference an 'empty-result retry from the base class' (`providers/anthropic.py:35`, `model_providers/openai_compatible.py:128`), but no implementation in the 127 scanned files uses retry vocabulary. If that behaviour exists it is written without a single retry-shaped identifier, and no name-based method — ours or any other — would find it. Recorded as a detector-correct case with that caveat.

## 17. `SandAI-org/MagiAttention`

- repo: https://github.com/SandAI-org/MagiAttention
- search: https://github.com/search?type=code&q=repo%3ASandAI-org/MagiAttention+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: `meta/algorithms/{snf,fast_snf,binary_greedy,binary_greedy_parallel}.py` set `max_attempts = 1` and loop `for _attempt in range(max_attempts)`. This re-runs a local solver, not a call to a dependency, and at `max_attempts = 1` it does not retry at all.

## 18. `maze-agent/Maze`

- repo: https://github.com/maze-agent/Maze
- search: https://github.com/search?type=code&q=repo%3Amaze-agent/Maze+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `workflows/gaia/vision.py:18` passes `max_retries=1` — a literal the `generic_max_retries` rule is written to catch, so this is a miss on a covered pattern, not only on an exotic one. `maze/core/scheduler/scheduler.py:2888` and `maze/core/worker/worker.py:122,155` add hand-rolled attempt loops, and the scheduler models a `retrying` task state throughout.

## 19. `ByteDance-Seed/Triton-distributed`

- repo: https://github.com/ByteDance-Seed/Triton-distributed
- search: https://github.com/search?type=code&q=repo%3AByteDance-Seed/Triton-distributed+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: One docstring at `language/extra/cuda/tma_language.py:210` describing a CUDA barrier that 'retries until the predicate is true' — a hardware spin-wait, not a service retry. The 23 other matches are all under non-production paths.

## 20. `pytest-dev/pytest-xdist`

- repo: https://github.com/pytest-dev/pytest-xdist
- search: https://github.com/search?type=code&q=repo%3Apytest-dev/pytest-xdist+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: One comment at `src/xdist/dsession.py:441`: `# XXX count no of failures and retry N times`. An unimplemented TODO.

## 21. `canonical/snapcraft`

- repo: https://github.com/canonical/snapcraft
- search: https://github.com/search?type=code&q=repo%3Acanonical/snapcraft+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 1,090 source files scanned and zero production matches; the 8 matches are all in test paths. Store interaction is delegated to the separate `craft-store` package, so the retry policy lives outside this repository. A genuine true negative for this repo, and an illustration of how dependency boundaries hide policy from per-repository analysis.

## 22. `palahsu/DDoS-Ripper`

- repo: https://github.com/palahsu/DDoS-Ripper
- search: https://github.com/search?type=code&q=repo%3Apalahsu/DDoS-Ripper+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 3 source files, no match.

## 23. `ml-tooling/opyrator`

- repo: https://github.com/ml-tooling/opyrator
- search: https://github.com/search?type=code&q=repo%3Aml-tooling/opyrator+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 48 source files, no match.

## 24. `Hecate2/Ignareo-ISML-auto-voter`

- repo: https://github.com/Hecate2/Ignareo-ISML-auto-voter
- search: https://github.com/search?type=code&q=repo%3AHecate2/Ignareo-ISML-auto-voter+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed, and the most consequential one.** `DestroyerIGN/retryapi.py:15` vendors a full retry implementation — `__retry_internal(f, exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1, jitter=0, ...)` — carrying **both backoff and jitter parameters**. `ISMLnextGen/retryTest.py:19` defines a second `retry(*exceptions, retries=3, cooldown=1)` decorator, applied at `getTest.py:40`. Since the paper reports jitter appearing exactly once in 113 detected configurations, a missed jitter-capable implementation bears directly on that count.

## 25. `HDFGroup/h5pyd`

- repo: https://github.com/HDFGroup/h5pyd
- search: https://github.com/search?type=code&q=repo%3AHDFGroup/h5pyd+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed, on a covered pattern.** `h5pyd/_hl/httpconn.py:23` imports `from requests.adapters import HTTPAdapter, Retry` and constructs `retry = Retry(...)` at line 731 — the urllib3 form the `python_urllib3` rule exists to detect. `files.py:280` defaults `retries=10` and `folders.py:85` defaults `retries=3`, both documented as 'Number of retry attempts to be used if a server request fails'.

## 26. `team-ocean/veros`

- repo: https://github.com/team-ocean/veros
- search: https://github.com/search?type=code&q=repo%3Ateam-ocean/veros+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 149 source files, no match. Ocean-model numerics.

## 27. `DEAP/deap`

- repo: https://github.com/DEAP/deap
- search: https://github.com/search?type=code&q=repo%3ADEAP/deap+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 134 source files, no match. Evolutionary-algorithm library.

## 28. `yandex/yandex-taxi-testsuite`

- repo: https://github.com/yandex/yandex-taxi-testsuite
- search: https://github.com/search?type=code&q=repo%3Ayandex/yandex-taxi-testsuite+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: y
- notes: **Missed.** `testsuite/utils/net.py:108` takes `retries=15` and loops `for _ in range(retries)` waiting for a port to accept connections, documented as retrying `retries` times. This is production code of the testing framework, not a test fixture within it.

## 29. `rqlite/pyrqlite`

- repo: https://github.com/rqlite/pyrqlite
- search: https://github.com/search?type=code&q=repo%3Arqlite/pyrqlite+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: `src/pyrqlite/_ephemeral.py:68` loops `while self._proc is None` retrying local port allocation, and `connections.py:191` exposes `ping(reconnect=True)`. The loop retries acquisition of a local resource rather than a call to a dependency, and carries neither an attempt bound nor a backoff, so it is not a retry configuration in the sense tabulated. A stricter reading would count this as a miss; recorded as detector-correct with the boundary stated.

## 30. `GoogleCloudPlatform/cloud-run-microservice-template-python`

- repo: https://github.com/GoogleCloudPlatform/cloud-run-microservice-template-python
- search: https://github.com/search?type=code&q=repo%3AGoogleCloudPlatform/cloud-run-microservice-template-python+retry+OR+retries+OR+backoff+OR+reconnect
- language: Python
- verdict: n
- notes: 10 source files, no match. A Cloud Run template; retry is left to the platform.
---

## What this implies for the reported prevalence

The paper reports that 11.5% of the 200 repositories (23) contain explicit retry
logic, and states that this figure is a floor. This sample puts a number on how
far below the true value that floor sits.

Of the 177 repositories where nothing was detected, this sample of 30 finds
33.3% do contain retry logic (Wilson 95% CI 19.2%--51.2%). Extrapolating:

| False-negative rate | Estimated repositories with retry logic | Prevalence |
|---|---|---|
| 19.2% (CI low)  | 23 + 34 = 57 | 28.5% |
| 33.3% (point)   | 23 + 59 = 82 | **41.0%** |
| 51.2% (CI high) | 23 + 91 = 114 | 56.8% |

So the true prevalence is plausibly around 41%, roughly 3.5x the reported 11.5%,
and the paper's "11.5% is a floor" is directionally right but understates the
gap by a wide margin.

Three consequences worth weighing before this is used:

1. **Section IV-B currently says no false-negative rate is reported.** That
   sentence is now inconsistent with this file and must either be replaced with
   the measured rate or this file must be excluded from the artifact.

2. **The detected 113 configurations are not a random sample of retry code.**
   They are a sample of retry code *written in library idioms the rules cover*.
   Hand-rolled loops dominate the misses here, and hand-rolled loops rarely carry
   jitter or capped backoff, so the configuration-level shares in Table II are
   plausibly biased — though the direction is not obvious, and item 24 shows a
   missed implementation that does carry both backoff and jitter parameters.

3. **Two misses (18, 25) are on covered patterns** (`generic_max_retries` and
   `python_urllib3`). Those are detector bugs rather than scope limits, and are
   worth fixing before any follow-up run: they imply the recall problem is not
   solely "we did not write a rule for hand-rolled loops."

None of this touches the simulation results or the ARB evaluation, which do not
depend on the repository study.
