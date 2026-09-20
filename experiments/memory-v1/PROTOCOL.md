# Memory v1: preliminary retrieval-mechanism ablation

This independent synthetic development experiment follows the routing baseline.
It uses no routing calibration or held-out cases, no production memory, no model
calls, no cloud spending and no installed service. Results are provisional. This
is not a comparison of Calyx's full persistent memory system or a task-success
evaluation. Game AI is outside this experiment.

## Frozen design

Eight independently specified synthetic past executable outcomes are stored in
an immutable in-process history. Twenty-four explicit queries cover exact
repeats, harmless prose changes, repeated failures, numeric-value collisions,
stale revision evidence, different artifact or command, untrusted and missing
proof, conflicting results and unknown scope. The scenarios concern synthetic
weaving, bookbinding, audio, paper-folding and score fixtures. They were authored
for this experiment and do not reuse the routing benchmark's scenario text.

The four arms receive exactly the same canonical JSON public state:

1. No memory: no candidate and a raw `review` recommendation.
2. Exact cache: reuse only an identical entire public state.
3. Simple token Jaccard: lowercased identifier and numeric tokens; set Jaccard.
4. Stock Calyx `FlyLSHHasher`: unmodified feature extraction and active-cell
   overlap from the locally available v1.0.7 source. Default dimensions 64 and
   2048, 102 active cells, seed 42. This is a hasher retrieval arm, not a modified
   numeric-value-preserving adapter or the full Calyx product.

Both approximate arms use threshold **0.8**, selected as a simple convention
before running this dataset. It is not calibrated and will not be tuned from
these outcomes. Exact cache requires exact equality. Highest similarity wins;
ties use original history order. Histories contain fixed author-specified
outcomes and receive no updates or reinforcement from queries.

`prepare` validates labels against the existing trusted executable contract and
writes the explicit dataset and definition hashes before outcome measurement.
The definition binds source, evaluator, protocol, code, thresholds and repeats.
Any subsequent change requires a new version/run and fresh evaluation cases if
used for held-out claims. The current study is development mechanism evidence.

## Recommendations and actions

A candidate's saved action is a **raw reused recommendation**, including a saved
failure or review. With no hit, the raw action is review. The unchanged routing
evaluator's `machine_gate` governs the action boundary: an unmet or uncertain
prerequisite overrides a skip; a valid current gate does not turn a raw refusal
into a skip. This equals the executable action behavior of existing enforcement
without fabricating model probability distributions.

Record candidate hits, raw action mismatches, raw unsafe skips, raw skips on stale
proofs, mismatched candidate binding, enforced unsafe skips and correctly granted
skips. Keep every query, including abstentions and collisions. Two explanations
with close features do not supply authority to reuse a proof.

For transparency also report the deterministic gate by itself. These fixtures
are all executable, so that gate can already decide every action without a
model. Calling a hit one **simulated fallback call avoided** is only bookkeeping
under a hypothetical query-on-miss policy. There are zero actual model calls;
actual calls avoided, token savings, total-task savings and cost savings remain
unknown. No measured benefit over the deterministic gate is implied.

## Timing and resources

Build immutable history representations once, recording build time separately.
Record Calyx import and initialization separately from index build. Perform one
untimed first-query warmup per arm, followed by 31 lookup repetitions of each
query. Rotate arm order by query plus repetition. Lookup timing includes query
serialization, query representation and candidate search. It excludes index
construction, enforcement and any hypothetical fallback. Preserve all timings.

Report nearest-rank p50/p95 across lookup timings and across per-query medians,
repeated-output changes, process CPU and elapsed time, projection-array bytes,
Python/NumPy versions and requested BLAS thread limits. Repetitions do not change
the sample size of 24 dependent, curated queries. Peak process memory is unknown
unless independently measured; array size is not a process-memory measurement.
No statistical significance or general latency superiority is claimed.

## Pinned source and private-data boundary

Prior local review attributes v1.0.7 to commit
`05d5dddf2c66b82e40fcbc40502a01e6336314be`. The unpacked local source has no `.git`,
so this is inherited commit provenance, not a newly verified Git checkout. This
run directly verifies the following exact source bytes:

| File | SHA-256 |
| --- | --- |
| config.py | 28ca4a47cf4953b08e78b0c912fa48dc9796d0d63cf85b30b2f01dc2044099d9 |
| hasher.py | bbd91d602e055907c177dd3ef393eb6510979cda96c8e23e39fa28feea5ea52c |
| LICENSE | 16d1ce2cf935d55314a6e975bf71e22937520b921517e44839efc29b9d196a7d |

Only those two Python modules are loaded through an isolated package shell.
Calyx's package initializer, memory storage, server, installer and configuration
readers are not run. No user's `.calyx` files or MCP settings are read or written.
No implementation is vendored. License: MIT, copyright 2026 Calyx Research Team.
NumPy is already bundled; no installation or model download is required.

## Reproduction

Run tests using an existing Python interpreter with bundled NumPy. Set
`CALYX_REVIEW_SOURCE` and `ALDERTRACE_EVALUATOR` to the pinned source directory and
existing `study/core.py` for the optional direct source checks.

```sh
python -B -m unittest -v test_memory_ablation
python -B memory_ablation.py prepare --output /new/disposable/result-directory --calyx-source /existing/calyx-source --evaluator ../study/core.py --protocol ../experiments/memory-v1/PROTOCOL.md
python -B memory_ablation.py run --output /new/disposable/result-directory --calyx-source /existing/calyx-source --evaluator ../study/core.py --protocol ../experiments/memory-v1/PROTOCOL.md
```

Outputs are write-once. `STARTED.json` precedes measurement, and `COMPLETE.json`
attests completed raw, summary and failure files. Interrupted or failed runs
remain visibly incomplete and are not silently reused. Preserve them and create
a new versioned run for another attempt. Synthetic failures are not fed back
into any user's memory. No author contact, publication, push or installation is
authorized by this experiment.
