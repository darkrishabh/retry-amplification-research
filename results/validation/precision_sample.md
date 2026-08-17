# Precision check

Seeded random sample of 30 detected retry configurations drawn from 162 total findings (seed 20260814).

For each item: open the link, read the surrounding code, and decide whether
this is genuinely a retry configuration. Replace `verdict: ?` with:

  - `y` - genuine retry configuration
  - `n` - false positive (e.g. a variable that merely contains 'retry')

Also sanity-check the extracted fields; note anything wrong in the `notes` line.

---

## Provenance of the verdicts below

**These verdicts were produced by a tool-assisted pass, not by an unaided human
read. Reviewed and signed off by the corresponding author (R. Mehan), 16 August
2026; the authors take responsibility for them.** What was done:
each file was fetched from `raw.githubusercontent.com/{repo}/HEAD/{path}`, the
recorded evidence string was located in the current text (line numbers have
drifted since the January analysis, so the string rather than the line number
anchors each item), and the surrounding code was read. Every verdict below
quotes the construct it rests on, so confirming an item means comparing the
quoted line against the linked source rather than re-deriving it.

This supersedes the earlier tally in `ai_prescreen.md` in two ways, both
recorded there:

1. **Item 24 is no longer unresolvable.** `modal-client` moved its package into
   a `py/` directory; the file is `py/modal/volume.py` at HEAD and still carries
   the retry decorator. All 30 items now resolve.
2. **`ai_prescreen.md` double-counted item 4.** It reported "28 genuine of 29
   resolvable = 96.6%" and then "counting item 4 as a false positive gives 27/29
   = 93.1%" — but the 28 had *already* excluded item 4, so those were the same
   case stated twice. The 93.1% lower bound was an arithmetic slip.

**Tally: 29 genuine of 30 = 96.7%.** The single exception is item 4. If item 4
is counted as a configuration, precision is 30/30 = 100%; 96.7% is the
conservative reading and the one the paper reports.

**Field-extraction errors are separate from precision** and are noted per item.
Three appear in this sample (items 6, 12, 30). All three fall on detections that
the non-production path filter already excludes, so none of them reaches the 113
production configurations in Table II. That is reassuring but not a guarantee:
this sample was drawn from the raw 162, so it does not bound the field-error
rate within the cleaned set.

---

## 1. `hatchet-dev/hatchet`

- url: https://github.com/hatchet-dev/hatchet/blob/HEAD/examples/typescript/retries/workflow.ts#L15
- file: `examples/typescript/retries/workflow.ts:15`
- pattern: `js_retries`
- extracted: max_retries=`3` backoff=`none` jitter=`False`
- evidence: `retries: 3`
- verdict: y
- notes: `retries: 3` inside `hatchet.task({...})` — a real task-level retry config. The file has two identical `retries: 3` blocks (lines 6 and 15); this is the second. Non-production (`examples/`), so excluded from the 113.

## 2. `nvidia-cosmos/cosmos-curate`

- url: https://github.com/nvidia-cosmos/cosmos-curate/blob/HEAD/benchmarks/secrets.py#L35
- file: `benchmarks/secrets.py:35`
- pattern: `python_tenacity`
- extracted: max_retries=`None` backoff=`exponential` jitter=`False`
- evidence: `tenacity.retry`
- verdict: y
- notes: `@tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=15))`. Backoff correctly exponential; count 3 is present but not extracted. Non-production (`benchmarks/`).

## 3. `lzjever/routilux`

- url: https://github.com/lzjever/routilux/blob/HEAD/playground/retry_serialization_demo/showcase_scenarios.py#L228
- file: `playground/retry_serialization_demo/showcase_scenarios.py:228`
- pattern: `generic_max_retries`
- extracted: max_retries=`4` backoff=`linear` jitter=`False`
- evidence: `max_retries=4`
- verdict: y
- notes: `ErrorHandler(strategy=ErrorStrategy.RETRY, max_retries=4, retry_delay=0.3, retry_backoff=1.5, ...)`. `retry_backoff=1.5` is a multiplier, so this is arguably exponential rather than linear. Non-production (`playground/`).

## 4. `apidoorman/doorman`

- url: https://github.com/apidoorman/doorman/blob/HEAD/backend-services/services/gateway_service.py#L2281
- file: `backend-services/services/gateway_service.py:2281`
- pattern: `generic_max_retries`
- extracted: max_retries=`0` backoff=`none` jitter=`True`
- evidence: `max_retries = 0`
- verdict: n
- notes: **The one false positive.** Now at line 2461. `env_max_retries = 0` is a local initializer on the line immediately before `env_max_retries = int(os.getenv('GRPC_MAX_RETRIES', '0'))` — the effective retry count comes from the environment, so `0` is not a configured value. The surrounding block *is* genuine retry logic (`attempts`, `base_ms`, `max_ms`, `jitter = 0.5` at line 2470), which is also what produced the spurious `jitter=True`: the word `jitter` falls inside the +/-200 character context window. Counted as a false positive here, which is the conservative reading.

## 5. `modal-labs/modal-examples`

- url: https://github.com/modal-labs/modal-examples/blob/HEAD/06_gpu_and_ml/langchains/potus_speech_qanda.py#L66
- file: `06_gpu_and_ml/langchains/potus_speech_qanda.py:66`
- pattern: `generic_max_retries`
- extracted: max_retries=`3` backoff=`exponential` jitter=`False`
- evidence: `max_retries=3`
- verdict: y
- notes: `@app.function(retries=modal.Retries(max_retries=3, backoff_coefficient=2.0))`. Both fields correct — `backoff_coefficient=2.0` confirms exponential.

## 6. `AnubisLMS/Anubis`

- url: https://github.com/AnubisLMS/Anubis/blob/HEAD/theia/autograde/anubis_autograde/exercise/pipeline.py#L15
- file: `theia/autograde/anubis_autograde/exercise/pipeline.py:15`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`none` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: `@retry(tries=3)` from the `retry` package, on an HTTP call to `anubis-pipeline-api`. **Field error:** the count is stated as `tries=3` but extracted as `None`, so this configuration is missing from the 73-item retry-count denominator. Backoff genuinely absent.

## 7. `lzjever/routilux`

- url: https://github.com/lzjever/routilux/blob/HEAD/examples/retry_with_router_demo.py#L148
- file: `examples/retry_with_router_demo.py:148`
- pattern: `generic_max_retries`
- extracted: max_retries=`3` backoff=`none` jitter=`False`
- evidence: `max_retries=3`
- verdict: y
- notes: `retry_router = RetryRouter(max_retries=3)`. Non-production (`examples/`).

## 8. `open-edge-platform/edge-ai-libraries`

- url: https://github.com/open-edge-platform/edge-ai-libraries/blob/HEAD/sample-applications/video-search-and-summarization/search-ms/src/utils/utils.py#L36
- file: `sample-applications/video-search-and-summarization/search-ms/src/utils/utils.py:36`
- pattern: `generic_max_retries`
- extracted: max_retries=`3` backoff=`none` jitter=`False`
- evidence: `max_retries=3`
- verdict: y
- notes: Now at line 52: `def upload_single_video_with_retry(file_path, max_retries=3)`, driving `for attempt in range(1, max_retries + 1)` with a `time.sleep(backoff_time)`. A second identical default sits at line 106 (`submit_embedding_batch`).

## 9. `PrimeIntellect-ai/prime`

- url: https://github.com/PrimeIntellect-ai/prime/blob/HEAD/packages/prime-evals/src/prime_evals/evals.py#L254
- file: `packages/prime-evals/src/prime_evals/evals.py:254`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`exponential` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: Now at line 270: `@retry(retry=retry_if_exception(_is_retryable), stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=16), reraise=True)`. An async twin sits at line 604.

## 10. `VOLTTRON/volttron`

- url: https://github.com/VOLTTRON/volttron/blob/HEAD/volttron/utils/rmq_setup.py#L1113
- file: `volttron/utils/rmq_setup.py:1113`
- pattern: `generic_max_retries`
- extracted: max_retries=`12` backoff=`none` jitter=`False`
- evidence: `max_retries=12`
- verdict: y
- notes: Now at line 720: `def setup_rabbitmq_volttron(..., max_retries=12, env=None)`. A second `max_retries=12` default at line 866 (`_create_rabbitmq_config`). Twelve attempts with no backoff — one of the aggressive-retry cases.

## 11. `lzjever/routilux`

- url: https://github.com/lzjever/routilux/blob/HEAD/playground/retry_serialization_demo/retry_demo.py#L73
- file: `playground/retry_serialization_demo/retry_demo.py:73`
- pattern: `generic_max_retries`
- extracted: max_retries=`4` backoff=`linear` jitter=`False`
- evidence: `max_retries=4`
- verdict: y
- notes: `ErrorHandler(strategy=ErrorStrategy.RETRY, max_retries=4, retry_delay=0.3, retry_backoff=1.5, ...)`. Same construct as item 3, different file. Non-production (`playground/`).

## 12. `roma-glushko/hyx`

- url: https://github.com/roma-glushko/hyx/blob/HEAD/docs/snippets/retry/retry_backoff_expo.py#L9
- file: `docs/snippets/retry/retry_backoff_expo.py:9`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`linear` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: `@retry(on=httpx.NetworkError, backoff=expo(min_delay_secs=10, base=2, max_delay_secs=60))`. **Field error:** recorded as `linear`, but `expo(base=2)` is exponential. Non-production (`docs/`), so it does not affect Table II.

## 13. `roma-glushko/hyx`

- url: https://github.com/roma-glushko/hyx/blob/HEAD/docs/snippets/retry/retry_backoff_const.py#L8
- file: `docs/snippets/retry/retry_backoff_const.py:8`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`linear` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: `@retry(on=httpx.NetworkError, backoff=0.5)  # delay 500ms on each retry`. A constant delay; classifying it as `linear` rather than `none` is defensible. Non-production (`docs/`).

## 14. `zd87pl/ai-crypto-trader`

- url: https://github.com/zd87pl/ai-crypto-trader/blob/HEAD/services/neural_network_service.py#L1570
- file: `services/neural_network_service.py:1570`
- pattern: `generic_max_retries`
- extracted: max_retries=`15` backoff=`linear` jitter=`False`
- evidence: `max_retries=15`
- verdict: y
- notes: `await self.connect_redis(max_retries=15, retry_delay=2)`. Fifteen attempts at a fixed 2 s delay.

## 15. `celery/celery`

- url: https://github.com/celery/celery/blob/HEAD/celery/backends/gcs.py#L127
- file: `celery/backends/gcs.py:127`
- pattern: `generic_max_retries`
- extracted: max_retries=`3` backoff=`none` jitter=`False`
- evidence: `max_retries=3`
- verdict: y
- notes: `requests.adapters.HTTPAdapter(pool_connections=..., pool_maxsize=..., max_retries=3)` mounted on the GCS client session.

## 16. `open-edge-platform/edge-ai-libraries`

- url: https://github.com/open-edge-platform/edge-ai-libraries/blob/HEAD/microservices/time-series-analytics/src/opcua_alerts.py#L65
- file: `microservices/time-series-analytics/src/opcua_alerts.py:65`
- pattern: `generic_max_retries`
- extracted: max_retries=`10` backoff=`none` jitter=`False`
- evidence: `max_retries=10`
- verdict: y
- notes: Now at line 96: `async def connect_opcua_client(self, secure_mode, max_retries=10)`, documented as "Connect to OPC UA client with retry mechanism."

## 17. `zd87pl/ai-crypto-trader`

- url: https://github.com/zd87pl/ai-crypto-trader/blob/HEAD/services/ai_explainability_service.py#L62
- file: `services/ai_explainability_service.py:62`
- pattern: `generic_max_retries`
- extracted: max_retries=`10` backoff=`linear` jitter=`False`
- evidence: `max_retries=10`
- verdict: y
- notes: `async def connect_redis(self, max_retries=10, retry_delay=5)` driving `while retries < max_retries`.

## 18. `aws-samples/observability-with-amazon-opensearch`

- url: https://github.com/aws-samples/observability-with-amazon-opensearch/blob/HEAD/sample-apps/11-client/api/api.py#L159
- file: `sample-apps/11-client/api/api.py:159`
- pattern: `python_urllib3`
- extracted: max_retries=`2` backoff=`none` jitter=`False`
- evidence: `Retry(
    total=2`
- verdict: y
- notes: `Retry(total=2, status_forcelist=[401, 401.1, 429, 503], allowed_methods=[...])`. No `backoff_factor`, so `none` is correct — urllib3 defaults to zero backoff. Non-production (`sample-apps/`).

## 19. `AgnetLabs/Laddr`

- url: https://github.com/AgnetLabs/Laddr/blob/HEAD/lib/laddr/src/laddr/core/runtime_entry.py#L733
- file: `lib/laddr/src/laddr/core/runtime_entry.py:733`
- pattern: `generic_max_retries`
- extracted: max_retries=`10` backoff=`linear` jitter=`False`
- evidence: `max_retries = 10`
- verdict: y
- notes: `max_retries = 10` / `retry_delay = 1  # Start with 1 second`, consumed by `for attempt in range(max_retries)` around `connect_bus()`.

## 20. `celery/celery`

- url: https://github.com/celery/celery/blob/HEAD/t/integration/tasks.py#L237
- file: `t/integration/tasks.py:237`
- pattern: `generic_max_retries`
- extracted: max_retries=`1` backoff=`none` jitter=`False`
- evidence: `max_retries=1`
- verdict: y
- notes: Now at line 243: `@shared_task(bind=True, expires=120.0, max_retries=1)`. A genuine retry configuration, but a test fixture — non-production (`t/`), and one of the six detections the broadened path filter added.

## 21. `zd87pl/ai-crypto-trader`

- url: https://github.com/zd87pl/ai-crypto-trader/blob/HEAD/services/enhanced_social_monitor_service.py#L109
- file: `services/enhanced_social_monitor_service.py:109`
- pattern: `generic_max_retries`
- extracted: max_retries=`5` backoff=`linear` jitter=`False`
- evidence: `max_retries=5`
- verdict: y
- notes: `async def connect_redis(self, max_retries=5, retry_delay=5)` driving `while retries < max_retries`.

## 22. `hashview/hashview`

- url: https://github.com/hashview/hashview/blob/HEAD/install/hashview-agent/agent/http/http.py#L14
- file: `install/hashview-agent/agent/http/http.py:14`
- pattern: `python_urllib3`
- extracted: max_retries=`100` backoff=`linear` jitter=`False`
- evidence: `Retry(total=100`
- verdict: y
- notes: Now at line 12: `retries = Retry(total=100, backoff_factor=1)` mounted via `HTTPAdapter(max_retries=retries)` on both schemes. One hundred attempts — the most aggressive configuration in the sample.

## 23. `zd87pl/ai-crypto-trader`

- url: https://github.com/zd87pl/ai-crypto-trader/blob/HEAD/services/trade_executor_service.py#L1387
- file: `services/trade_executor_service.py:1387`
- pattern: `generic_max_retries`
- extracted: max_retries=`15` backoff=`linear` jitter=`False`
- evidence: `max_retries=15`
- verdict: y
- notes: `await self.connect_redis(max_retries=15, retry_delay=2)`, same shape as item 14.

## 24. `modal-labs/modal-client`

- url: https://github.com/modal-labs/modal-client/blob/HEAD/py/modal/volume.py
- file: `modal/volume.py:1295`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`linear` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: **Previously recorded as unresolvable; it is not.** `modal/volume.py` 404s at HEAD because the repository moved its package under `py/`. The file is `py/modal/volume.py` (1,575 lines) and still carries three retry decorators: `@retry(n_attempts=5, base_delay=0.1, attempt_timeout=None)` at lines 864 and 932, and `@retry(n_attempts=11, base_delay=0.5, attempt_timeout=None)` at line 1493. Genuine. Note the count is stated (`n_attempts`) but was extracted as `None`.

## 25. `OpenBMB/IoA`

- url: https://github.com/OpenBMB/IoA/blob/HEAD/im_client/agents/open_interpreter/open_interpreter_agent.py#L39
- file: `im_client/agents/open_interpreter/open_interpreter_agent.py:39`
- pattern: `generic_max_retries`
- extracted: max_retries=`5` backoff=`none` jitter=`False`
- evidence: `max_retries=5`
- verdict: y
- notes: `yield from litellm.completion(**params, max_retries=5, num_retries=5)`, itself nested inside a hand-rolled `while retries < max_retries` loop with `max_retries = 20` — a nested retry, so the effective attempt count is the product, not 5. Exactly the compounding the paper models.

## 26. `allenai/genesys`

- url: https://github.com/allenai/genesys/blob/HEAD/model_discovery/agents/search_utils.py#L718
- file: `model_discovery/agents/search_utils.py:718`
- pattern: `generic_max_retries`
- extracted: max_retries=`3` backoff=`linear` jitter=`False`
- evidence: `max_retries=3`
- verdict: y
- notes: `def search_arxiv(self, query, result_limit=10, category=[...], max_retries=3, retry_delay=1)`.

## 27. `open-edge-platform/edge-ai-libraries`

- url: https://github.com/open-edge-platform/edge-ai-libraries/blob/HEAD/microservices/dlstreamer-pipeline-server/user_scripts/gvapython/timestamp/ntp.py#L22
- file: `microservices/dlstreamer-pipeline-server/user_scripts/gvapython/timestamp/ntp.py:22`
- pattern: `generic_max_retries`
- extracted: max_retries=`10` backoff=`none` jitter=`False`
- evidence: `max_retries=10`
- verdict: y
- notes: `def _verify_connection(self, max_retries=10)` with `while not connected`. This is the canonical duplicate case: line 20 is the call `self._verify_connection(max_retries=10)` and line 22 the signature it resolves to — one policy, two detections, collapsed by the 10-line dedupe window.

## 28. `adidas/lakehouse-engine`

- url: https://github.com/adidas/lakehouse-engine/blob/HEAD/lakehouse_engine/utils/sharepoint_utils.py#L108
- file: `lakehouse_engine/utils/sharepoint_utils.py:108`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`exponential` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: Now at line 122: `@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=30, min=30, max=150), retry=retry_if_exception_type((RequestException, SharePointAPIError)))`. Correctly exponential; no jitter, consistent with the anti-pattern tally.

## 29. `OpenBMB/IoA`

- url: https://github.com/OpenBMB/IoA/blob/HEAD/im_client/server_helper.py#L56
- file: `im_client/server_helper.py:56`
- pattern: `python_decorator`
- extracted: max_retries=`None` backoff=`exponential` jitter=`False`
- evidence: `@retry(`
- verdict: y
- notes: `@retry(stop=stop_after_attempt(5), reraise=True, retry=retry_if_exception_type(RequestError), wait=wait_exponential(multiplier=1, min=1, max=10), before_sleep=log_retry)`. An identical decorator sits at line 27.

## 30. `hatchet-dev/hatchet`

- url: https://github.com/hatchet-dev/hatchet/blob/HEAD/sdks/python/hatchet_sdk/clients/rest/tenacity_utils.py#L24
- file: `sdks/python/hatchet_sdk/clients/rest/tenacity_utils.py:24`
- pattern: `python_tenacity`
- extracted: max_retries=`None` backoff=`exponential` jitter=`True`
- evidence: `tenacity.retry`
- verdict: y
- notes: Now at line 30: `tenacity.retry(reraise=True, wait=config.wait(), stop=stop_after_attempt(config.max_attempts), before_sleep=config.before_sleep, retry=retry_if_exception(should_retry))`. Genuine, but **field error:** `jitter=True` is wrong — the wait strategy is indirected through `config.wait()` and no randomization is visible here. This is one of the two `tenacity_utils.py` detections that the jitter correction removes.
