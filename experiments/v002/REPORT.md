# Aldertrace: evidence before autonomy

Provisional synthetic research. This report is generated from scored JSON artifacts; no inference is performed.

**Recommendation:** retain deterministic prerequisite enforcement; further-test semantic routing without claiming net savings. Do not adopt similarity as proof. The paired full-task pilot remains unmeasured.

## Development comparison

The three versions reuse the same 20 cases. D1 uses original instructions; D2 clarifies semantic evidence; D3 keeps D2 instructions and resolves executable checks deterministically before model calls. These are development iterations, not independent samples. Development definitions record a base commit plus implementation hashes; the base commit alone does not identify the uncommitted development source.

| Run / arm | Safe / eligible | Raw unsafe | Enforced unsafe | Calls | Request p50 / p95 ms | Estimated / reported cost | Net input proxy saved |
|---|---:|---:|---:|---:|---:|---:|---:|
| D1 / Chat model | 4/9 | 3/11 | 0/11 | 20 | 1,115.0 / 1,325.4 | $0.00459 / $0.00459 | -11,919 |
| D1 / Jev | 4/9 | 0/11 | 0/11 | 20 | 389.3 / 436.8 | $0.0004909 / Unknown | -5,787 |
| D2 / Chat model | 9/9 | 2/11 | 0/11 | 20 | 1,124.8 / 1,512.6 | $0.0052668 / $0.0052668 | -13,240 |
| D2 / Jev | 9/9 | 0/11 | 0/11 | 20 | 428.0 / 486.2 | $0.00055978 / Unknown | -7,108 |
| D3 / Chat model | 9/9 | 0/4 | 0/11 | 9 | 1,086.5 / 1,266.7 | $0.0022052 / $0.0022052 | -5,136 |
| D3 / Jev | 8/9 | 0/4 | 0/11 | 9 | 408.0 / 489.5 | $0.00023453 / Unknown | -2,666 |

D3 retained chat coverage but Jev declined from 9/9 to 8/9 eligible skips. This regression remains visible. Raw model denominators exclude deterministic bypasses in D3. Request-only latency excludes those bypasses; a mixed policy median is not model latency.

The input proxy counts exact guides and observable public requests with a frozen tokenizer, including primary retries. It preserves negative outcomes. Hidden provider serialization remains unknown, so actual net-token reduction and H1 remain unknown. No full-task success or H3 measurement exists.

## Held-out evaluation

Frozen source commit: `43b014deec0ba87078bf97c50aa5c3ec725ef351`. Unique test cases: 80. Thresholds: `{"chat": 1.0, "jev": 0.6}`. Labels remain provisional.

| Arm | Safe / eligible | Raw unsafe | Enforced unsafe | Semantic safe / eligible | Repeat raw / enforced changed |
|---|---:|---:|---:|---:|---:|
| Chat model | 20/40 | 7/20 | 0/40 | 0/20 | 1 / 1 among 20 repeated cases |
| Jev | 34/40 | 0/20 | 0/40 | 14/20 | 0 / 1 among 20 repeated cases |
| read_everything | 0/40 | — | 0/40 | 0/20 | Deterministic by construction, not timed |
| deterministic | 20/40 | — | 0/40 | 0/20 | Deterministic by construction, not timed |
| Local scoring | Unknown | Unknown | Unknown | Unknown | Not executed after resource stop |

The prespecified selection rule was: zero observed unsafe semantic skips; maximize safe coverage; tie high. Calibration raw unsafe recommendations were 3/20 for chat and 3/20 for Jev. The selected operating thresholds were chat 1.00 and Jev 0.60. On held-out cases, the chat threshold rejected its 7 unsafe recommendations, but also rejected all 18 correct semantic skip recommendations: enforced coverage 0/20. Jev retained 14/20 semantic coverage. Threshold selection is not probability calibration; no post-test retuning occurred.

The operator was not fully blinded: a source-blinding diagnostic printed the tail of held-out source/labels after all three development choices had been selected but before freeze. No prompt, policy or dataset change followed that exposure. No tuning used held-out outcomes.

| Test arm | Primary requests | Request wall p50 / p95 ms | All attempts incl. repeats | Native input / output | Estimated / reported cost | Net input proxy saved |
|---|---:|---:|---:|---:|---:|---:|
| Chat model | 40 | 1,143.3 / 1,495.7 | 60 | 27292 / 2400 | $0.0147568 / $0.0147568 | -24,554 |
| Jev | 40 | 391.0 / 494.7 | 60 | 37358 / 2760 | $0.00156904 / Unknown | -12,240 |

The net input proxy covers primary observations including their retries. Native usage and cost cover every attempt, including repeats. Request wall time includes driver overhead and excludes bypasses. Baseline runtime and end-to-end cost are unknown.

| Test family | Jev safe / eligible | Chat safe / eligible | Jev / chat enforced unsafe |
|---|---:|---:|---:|
| browser-policy | 10/10 | 10/10 | 0/10 / 0/10 |
| compressed-streams | 7/10 | 0/10 | 0/10 / 0/10 |
| experimental-assignment | 7/10 | 0/10 | 0/10 / 0/10 |
| laboratory-instruments | 10/10 | 10/10 | 0/10 / 0/10 |

Paired Jev minus chat: +14 safe skips, +35.0 percentage points, +0 enforced unsafe skips on 80 matched unique cases. Paired mixed-policy median latency difference -234.7 ms; mean-latency whole-family bootstrap interval [-750.9864249999999, -0.001875] ms. This timing comparison includes bypasses and must not be read as inference latency.

Family and paired results are preserved in `evidence.json`. Whole-family bootstrap uncertainty is exploratory with four authored test families, only two semantic families. Repeats do not increase the unique sample size. Zero observed errors cannot establish production safety or a tiny population error rate. No significance or calibrated-probability claim is supported. No post-test tuning is permitted; future experiments need new versions and fresh cases.

## Local arm and labels

Local run stopped: transport failure; no further automatic dispatch. It contains 7 journaled attempts, 6 with model telemetry, and 13 missing primary observations. It is not a complete matched local comparison. Local electricity/hardware cost is unknown.

Blind separate-agent review recorded 144/144 agreement. Human adjudication: False. This does not establish independent human validation; results remain provisional.


### Completed local/cloud intersection

Only 6 completed local requests have telemetry and the same v1 case inputs as D1 cloud. This resource-selected subset is a partial comparison, not a complete five-arm evaluation. The failed next request is not silently treated as a zero-cost, zero-latency model response.

| Arm | Safe / eligible | Raw unsafe | Enforced unsafe | Request wall p50 / p95 ms | Native input / output tokens |
|---|---:|---:|---:|---:|---:|
| Chat model | 0/3 | 2/3 | 0/3 | 1,216.1 / 1,428.3 | 2382 / 240 |
| Jev | 0/3 | 0/3 | 0/3 | 375.8 / 392.7 | 3417 / 278 |
| Local scoring | 0/3 | 0/3 | 0/3 | 3,802.1 / 4,455.6 | 1722 / 6 |

Local: 6 cold requests, model-load p50 2,864.2 ms; warm throughput unknown. Native model tokenizers differ. Baseline execution latency and local energy costs remain unknown.

## Separate memory mechanism comparison

24 unique synthetic queries; 8 fixed history records. No reinforcement, persistent Calyx state, MCP overhead, or model fallback was measured.

| Arm | Hits | False action reuse | Raw unsafe | Enforced unsafe | Safe / eligible | Per-query median p50 ms |
|---|---:|---:|---:|---:|---:|---:|
| exact_cache | 8/24 | 0 | 0/16 | 0/16 | 4/8 | 0.0215 |
| no_memory | 0/24 | 0 | 0/16 | 0/16 | 0/8 | 0.0012 |
| stock_calyx_flylsh | 22/24 | 9 | 9/16 | 0/16 | 8/8 | 0.7439 |
| token_jaccard | 24/24 | 10 | 10/16 | 0/16 | 8/8 | 0.0982 |

Deterministic reference: 24/24 action matches with 0 model calls. A retrieval hit is simulated fallback avoidance, not actual model/token/cost savings. The experiment does not establish Calyx product efficacy or superiority.

## Budget and reproducibility

Cloud reservation ledger: `{"cap_usd": "2", "halted": false, "meaning": "Conservative reserved upper bounds, not actual provider spend.", "remaining_reserved_usd": "1.41250", "reserved_usd": "0.58750"}`.
Local allowance ledger: `{"cap_seconds": "3600", "charged_seconds": "40.7330000000074499", "halted": false, "pending_reservations": 0}`.

The snapshot preserves conservative reservations separately from measured provider totals. Unknown monetary amounts stay unknown. Per-run commits, dataset hashes, settings, samples, retries, native usage, and stop status are in `EXPERIMENT_LOG.csv` and `evidence.json`.

Regenerate offline from the original artifact root into a new directory:

```sh
python -B build_evidence_demo.py --root ARTIFACT_ROOT --output NEW_OUTPUT_DIRECTORY --heldout ARTIFACT_ROOT/campaign/v002-test-report
```

Frozen full-phase replay is currently supported on Windows/Python 3.12.14: threshold journal keys preserve Windows separators, and the recorded tokenizer wheel is CPython 3.12 Windows. Do not claim cross-platform full replay. A portability fix needs a new instrument version; this presentation itself uses only the Python standard library. Original scoring reports replay through `study-execution/development_report.py` with the run directory, split-specific dataset and existing frozen tokenizer environment. Locked phases verify the prospective freeze before replay; existing source and dependencies suffice without inference.

This presentation generator is outside the frozen experiment implementation. It only renders already-scored evidence. `MANIFEST.json` binds its source, presentation outputs, and input JSON hashes. Repositories remain private; no publication or external message is performed.

Game-AI acceptance criteria and full-task agent pilots remain separate, unexecuted studies.

Current provider-reported known subtotal: $0.0368812. Current reported-or-estimated subtotal: $0.04079896. Historical actual spend remains unknown; $0.1 is reserved for it. Provider response costs are not invoices. No unresolved reservations remain in the receipt. Local execution remains stopped.

Portable export links: [frozen settings](evidence/campaign/v002-frozen/freeze.json), [threshold selection](evidence/campaign/v002-frozen/thresholds.json), [test replay](reports/v002-test-report/report.json), [calibration replay](reports/v002-calibration-report/report.json), [budget receipt](evidence/campaign/budget-receipt-final.json), [label-review aggregate](label-review/aggregate-summary.json), [memory evidence](../memory-v1/evidence/summary.json), [protocol amendment](PROTOCOL-AMENDMENT.md).

To regenerate this presentation from the exported layout, run `python -B build_evidence_demo.py --root . --output NEW_OUTPUT_DIRECTORY --heldout reports/v002-test-report`. Link targets assume these files live at experiments/v002; root packaging preserves that layout. Input JSON hashes are the same in both layouts.

## Further-test recommendation

The intended building stack assigns prerequisite order to agent-syllabus, evidence enforcement to Aldertrace, and bounded semantic routing to Jev; tools and coding agents implement changes. This study does not establish near-free building, most work being automated, or lower cost per accepted change. Retain deterministic enforcement, reject semantic similarity as permission, and investigate the routing-overhead weakness with a new version and fresh cases. Before a real development pilot, satisfy advancement criteria and obtain human label review; then measure a repeatable workflow by total cost per accepted change, including retries, repairs, failed attempts and human intervention. No pilot is launched here.
