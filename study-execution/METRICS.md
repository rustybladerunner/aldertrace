# Performance evidence

The current artifact is the [v002 comparison and graphs](../experiments/v002/index.html),
with the [full report](../experiments/v002/REPORT.md) and
[versioned experiment log](../experiments/v002/EXPERIMENT_LOG.csv).
Its cloud held-out routing phase is complete. Actual end-to-end task outcomes and the
local-model comparison remain unfinished.

## Frozen v002 held-out results

There are 80 unique synthetic cases in four scenario families: 40 semantic and 40
executable cases, with 40 eligible and 40 prohibited skips. Twenty hash-selected cases
have three observations each; repeat observations do not enlarge the unique sample size.
The selected policy applies deterministic executable checks first and routes semantic
cases with the frozen v2 prompt. A bypassed case has no raw model recommendation.

| Enforced policy | Safe skips / 40 eligible | Unsafe skips / 40 prohibited |
| --- | ---: | ---: |
| Read everything | 0/40 | 0/40 |
| Deterministic rules | 20/40 | 0/40 |
| Jev plus deterministic checks | 34/40 | 0/40 |
| Conventional chat plus deterministic checks | 20/40 | 0/40 |
| Local scoring | Not measured on held-out | Not measured on held-out |

Jev's semantic safe coverage is 14/20 (70%); the other measured enforced policies
skip 0/20 eligible semantic cases. Raw semantic recommendations proposed 0/20
prohibited skips for Jev and 7/20 for chat. These raw counts must not be presented as
enforced actions. The phase-locked thresholds are Jev 0.6 and chat 1.0; they were
selected on calibration cases, not tuned on test. Selection is not probability calibration.

Labels remain provisional. A separate agent reviewed all 120 semantic and a stratified
24 executable cases before comparing its committed judgments with authored labels:
144 agreements, no reported disagreement or ambiguity. This is not human adjudication.
The report records the operator-blinding limitation. Four authored, correlated families
and zero observed enforced failures do not establish population safety or significance.
Use paired differences, family breakdowns and exploratory uncertainty from the report.

## Measurement boundaries

- **Tokens:** provider-native input/output usage and common-tokenizer observable-input
  proxies are separate measurements. The full public serialized request is observable;
  hidden provider prompt wrappers are not. Include every attempt and retry. Both cloud
  arms have a negative input-only net proxy. Actual net agent-token reduction remains
  unknown; H1 is not established. See [TOKENIZER.md](TOKENIZER.md).
- **Task success:** unknown. Routing-label agreement and accepted evidence reuse are
  not downstream task acceptance. Executable-check bypasses do not imply invented
  reading-token or runtime savings.
- **Cost:** reported conventional-provider charges, price-based Jev estimates and
  conservative campaign reservations are different quantities. Jev reported monetary
  cost is unknown. The campaign ledger includes preflights, development, calibration,
  test, repeats and a conservative historical allowance; a test-only total is not
  the campaign spend.
- **Latency:** the report contains observed router p50/p95 and paired measurements.
  Baseline runtime and complete task latency remain unknown. Local observations used
  cold requests with `keep_alive=0`; local execution stopped on resource guards and
  has no calibration/test result.
- **Stability:** among 20 repeated cases, Jev raw recommendations changed on 0 and chat
  on 1; enforced actions changed on 1 case for each arm. Threshold-sensitive confidence
  can change enforcement even when the raw choice is stable.

## Separate memory ablation

The [memory protocol](../experiments/memory-v1/PROTOCOL.md) covers 24 unique synthetic
queries, four memory arms and a standalone evidence-gate control. Calyx raw reuse was
unsafe on 9/16 prohibited queries; simple similarity on 10/16. All enforced arms had
zero observed unsafe reuse, and the gate alone made all 24 decisions correctly on
these fixtures. Repeated lookup timings do not increase the independent sample size.
Model calls were zero; actual calls avoided, task success and token/cost savings are
unknown. The experiment measures retrieval mechanisms, not the complete Calyx product.

## Original development baseline and instrument checks

The original draft baseline remains reproducible without models or credentials:

```sh
cd study-execution
python -B metrics_report.py --output development-metrics.json
```

This new-file-only output verifies the original draft manifest and recomputes its two
baselines on development cases. Deterministic checks reuse 20 valid executable passes
among 80 cases: 20/40 eligible skips and 0/40 observed unsafe skips. Semantic reading
avoided is zero bytes. This historical fixture result and the original runner's fake
responses are not new model performance observations.

## What would count as a gain?

Protocol targets remain at least 20% net onboarding-token reduction and at least a
10-point semantic safe-coverage improvement, with their specified constraints. The
observed semantic coverage difference is provisional; the token target is unestablished.
Do not hide negative proxies or replace missing measurements with zero-height bars.
Advancing to a real paired-task pilot requires the outstanding evidence, not a stronger
claim about this fixture. Future tuning needs a new version and fresh evaluation cases.
Game-AI studies require separate task metrics and acceptance criteria.
