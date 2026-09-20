# Study runner: current v002 execution and offline replay

The [v002 comparison](../experiments/v002/index.html), [report](../experiments/v002/REPORT.md)
and [experiment log](../experiments/v002/EXPERIMENT_LOG.csv) contain the completed
provisional cloud development, calibration and held-out routing phases. Local execution
is incomplete and stopped. Full downstream task success and actual net token savings
remain unknown. Frozen evaluation assets and earlier journals must remain unchanged.

## Current v2 path

`live_development.py` is the live entry point despite its historical name. It uses
`development.py` for the phase-aware run and `experiment_v2.py` for freeze verification.
Without `--execute`, it emits a plan and dispatches no requests. Live execution requires
separate authorization and explicit campaign, local-budget and output paths; it must
reuse the existing USD 2 and 3600-second campaign ledgers. `--create-budgets` is only for
the initial ledger creation, never a way to reset remaining capacity. There is no default
dependency installation, model download or automatic interrupted-run reconciliation.

The v002 sequence was:

1. Record three development iterations with preserved prompts and reports.
2. Freeze dataset, implementation, resolved model/settings identities, prompt, policy,
   measurement scope and threshold-selection rule before calibration.
3. Run all calibration cases, independently reparse responses, and freeze the selected
   thresholds plus calibration journal hashes. Jev selected 0.6; chat selected 1.0.
4. Verify those identities before the one-shot held-out phase. Run all 80 cases and
   repeat the preselected 20 cases twice more. Do not reopen test or tune on its results.

The selected policy is `deterministic_first`: matched executable cases use the evidence
checks without model dispatch; semantic cases use the frozen v2 prompt. Jev and chat
are the available frozen model arms. The local arm is explicitly unavailable for
calibration/test after resource guards stopped development execution. The unused local
time allowance is not a restart instruction. Cold local observations, incomplete cases
and resource telemetry remain in the evidence export.

The write-once locks are exported under
`experiments/v002/evidence/campaign/v002-frozen/`. Preserve their original bytes and
source commit (`43b014d`); frozen source/data integrity checks still apply. Documentation
and report export do not authorize changes to `.py`, the original protocol or study assets.

## Replay saved evidence without inference

From `study-execution/`, reparse the exported held-out journals into a new directory
outside the repository:

```sh
python -B development_report.py ../experiments/v002/evidence/campaign/v002-frozen/test --dataset ../study-v2/test.json --output <new-directory-outside-repository>
```

Add `--tokenizer-environment <approved-tokenizer-environment>` to reproduce the measured
observable-input proxy with the pinned installation. No tokenizer is downloaded by replay;
without its explicit environment the missing measurement stays unknown. See
[TOKENIZER.md](TOKENIZER.md). The saved report and tokenizer manifest remain available
for inspection without installing packages. Replay is not another evaluation and does
not consume inference budget. New output paths prevent overwriting earlier evidence.

## Original offline orchestrator

The following `runner.py` contract predates the live v2 path and remains covered by
instrument tests. Its fake-response counts are historical plumbing evidence.

`runner.py` connects the deterministic schedule, matched request adapters, durable
journals, shared campaign reservations, and definition/calibration locks. It accepts
injected transports; it does not load credentials or expose a live-execution CLI.

From this directory, reproduce the full sequence without network access or models:

```sh
python -B -m unittest -v test_runner.PhaseRunner.test_full_offline_sequence_and_no_test_reopening
```

This runs **840 fake responses**: 240 development, 240 calibration, and 360 held-out
requests including repeats, across three arms. The replies always abstain (`review`).
They prove orchestration, not intelligence, safety rates, latency, cost, or token savings.
The model/tokenizer attestations in these temporary test fixtures are explicitly fake.
No real evaluation is frozen or opened by this test.

## Original runner execution contract

1. A caller supplies separately authorized transports, resolved models, and one open
   `CampaignBudget` for the entire study, including preflight.
2. `run_phase(..., 'development', ...)` uses development cases only. Its output
   directory must be new and outside the source tree.
3. After actual development and prerequisite verification, freeze a definition in a
   separate experiment directory. Calibration refuses missing or changed definitions.
4. `calibration_bundles` validates request/case correspondence and independently
   reparses response bodies. Cached parsed answers are not trusted. Pass those bundles
   to `freeze_calibration` before opening the test phase.
5. The test phase requires matching definition and calibration locks. An exclusive
   phase directory and one-shot marker prevent automatic restart or duplicate execution.

Invalid responses and missing/excessive cloud usage stop the run and persistently halt
the campaign. Budget exhaustion leaves an incomplete phase with its existing evidence.
Neither condition authorizes retries in a fresh directory. Interrupted phases require
manual reconciliation; automatic resume remains unimplemented.

## Shared budget

`CampaignBudget(path, cap, create=True)` creates the first ledger exclusively. Later
phases reopen **the same path and cap**, without `create=True`. An OS lock permits only
one writer. Every attempt, including retries, is reserved and fsynced globally before
its local journal record and before dispatch. Reservations are never refunded; a crash
releases the OS lock but keeps uncertain charges. Corrupt/partial ledgers fail closed.

This is conservative local accounting, not a provider-enforced billing cap or defense
against someone deliberately deleting/replacing the ledger. A provider can report a
charge above its planned reservation; that response halts the campaign for review.

## What remains unfinished

Human label adjudication, Jev transport replication, a complete resource-compatible
local comparison and the real paired-task pilot remain unfinished. Threshold selection
does not establish calibrated probabilities; observable request serialization does not
establish actual net task-token savings. The current separate-agent review and cloud
held-out counts remain provisional. Consult the report before interpreting any graph.
Private GitHub publication grants no inference budget. Future experiments require a
new version and fresh evaluation cases, while retaining the same campaign accounting
unless the operator explicitly approves a different budget.

## Replay platform

The recorded campaign ran on Windows with Python 3.12.14. Full phase replay currently requires Windows because frozen calibration journal paths use backslashes. Do not rewrite frozen paths to make another platform pass. The export hash inventory can be verified on other platforms. The isolated tokenizer uses a CPython 3.12 Windows wheel; another platform needs separately versioned tokenizer provenance.
