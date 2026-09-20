# Offline analysis and replay

`analysis.py` computes raw and enforced action metrics, family counts, invalid-answer counts, multiclass Brier scores, exploratory reliability bins, descriptive Wilson intervals, whole-family bootstrap intervals, repeat stability and a case-level failure gallery. No backend runs are performed.

`replay_analysis.py` recomputes decisions from response bodies. It ignores the journal's cached `parsed` summary, verifies each request body against its mapped synthetic case, rejects duplicate results and unknown keys, and preserves unresolved reservations. The current reader accepts one arm's primary subset, not a mixed-arm journal. Exporting subsets must preserve all attempts for selected keys. A frozen manifest binding the journal, mapping and implementation is still required for a final result.

Example command from this folder, after genuine inference evidence exists:

```
python -B replay_analysis.py attempts.jsonl mapping.json --arm jev --expected-model jev-1.13.0 --threshold 0.95
```

The threshold shown above is an example only, not a selected policy. Obtain the real threshold from calibration and freeze it before held-out execution. `mapping.json` maps each logical request key to exactly one primary case ID. Three repeated observations of a case belong in the separate stability report; they do not count as three independent primary cases.

Offline validation:

```
python -B -m unittest -v test_analysis test_replay_analysis
```

These tests use development fixtures and fabricated responses. Their outputs are checks of the instrument, not evidence of model accuracy. In particular, the forced-skip test shows 20 unsafe raw recommendations on 20 non-skippable machine cases and zero granted after enforcement. It does not establish that any model is safe.

## Interpretation limits

- Invalid/missing responses are action `review`, with no fabricated probability vector. Brier scores omit invalid responses and disclose the remaining denominator. The failure gallery preserves invalid and unsafe cases.
- Raw recommendations and hybrid decisions have separate unsafe-skip denominators and counts. Abstention is not automatically an error.
- Wilson intervals assume independent Bernoulli trials, which correlated authored cases do not satisfy. Report this descriptive interval alongside family counts and whole-family resampling. With four test families, bootstrap intervals are exploratory; an all-zero bootstrap interval cannot establish zero population risk.
- Confidence bins and max-probability bins are separate. Local entropy concentration, Jev confidence and chat self-reported confidence are not automatically calibrated correctness probabilities.
- Replay latency sums attempt processing and recorded backoff, including retries. It excludes driver/journal overhead that was not recorded. Full end-to-end and cold-load measurements remain a live-driver requirement.
- Provider cost and tokenizer-based savings remain null. A budget reservation is not measured spend. Read direct Jev cost as estimated unless billing supports it. Usage reconciliation, frozen downstream tokenizer and measured adapter overhead are still outstanding.
- Paired cost/latency effects, plots, model-version validation at live preflight, and calibration/test execution locks remain to be implemented. No claim of completed comparative analysis is made by these modules.
