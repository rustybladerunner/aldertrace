# Experiment log — study v002

Generated from immutable scored reports and the final campaign receipt. Development is exploratory; calibration selects operating thresholds, not calibrated probabilities; held-out labels remain provisional. See [full data](EXPERIMENT_LOG.csv) and [hash manifest](MANIFEST.json).

| Run | Arm / model | Evidence | Unique planned / observed | All attempts / retries | Native input / output | Estimated / reported USD | Complete |
|---|---|---|---:|---:|---:|---:|---|
| D1 | chat / openai/gpt-4.1-mini | development | 20 / 20 | 20 / 0 | 8,267 / 802 | $0.00459 / $0.00459 | True |
| D1 | jev / jev-1.13.0 | development | 20 / 20 | 20 / 0 | 11,688 / 925 | $0.0004909 / Unknown | True |
| D2 | chat / openai/gpt-4.1-mini | development | 20 / 20 | 20 / 0 | 9,947 / 805 | $0.0052668 / $0.0052668 | True |
| D2 | jev / jev-1.13.0 | development | 20 / 20 | 20 / 0 | 13,328 / 925 | $0.00055978 / Unknown | True |
| D3 | chat / openai/gpt-4.1-mini | development | 20 / 20 | 9 / 0 | 4,073 / 360 | $0.0022052 / $0.0022052 | True |
| D3 | jev / jev-1.13.0 | development | 20 / 20 | 9 / 0 | 5,584 / 414 | $0.00023453 / Unknown | True |
| local-incomplete | local / llama3.2:latest | development | 20 / 7 | 7 / 0 | Unknown / Unknown | Unknown / Unknown | False |
| calibration-selection | chat / openai/gpt-4.1-mini | provisional-calibration | 80 / 80 | 40 / 0 | 18,246 / 1,600 | $0.0098584 / $0.0098584 | True |
| calibration-selection | jev / jev-1.13.0 | provisional-calibration | 80 / 80 | 40 / 0 | 24,806 / 1,840 | $0.00104185 / Unknown | True |
| heldout | chat / openai/gpt-4.1-mini | provisional-test | 80 / 80 | 60 / 0 | 27,292 / 2,400 | $0.0147568 / $0.0147568 | True |
| heldout | jev / jev-1.13.0 | provisional-test | 80 / 80 | 60 / 0 | 37,358 / 2,760 | $0.00156904 / Unknown | True |

Each development definition identifies its base commit plus exact implementation hashes; source_commit alone does not capture development edits. Frozen calibration/test use the full committed source below. Calibration report enforced actions use a null threshold and must not be read as post-selection coverage; the selected threshold record is separate.

The operator was not fully blinded: a source-blinding diagnostic printed the tail of held-out source/labels after all three development choices had been selected but before freeze. No prompt, policy or dataset change followed that exposure. No tuning used held-out outcomes.

## Version identities

### D1

- Code/base commit: `c7f95426fbeada5a840dcc155a14649b798b3214`
- Dataset SHA-256: `6c1db840e8e2bd49d0be9937169774f48161a961309fbae0e2536dfa320a72f6`
- Prompt / policy: `v1` / `all_cases`
- Settings: `{"chat_max_tokens": 512, "chat_seed": 20260919, "chat_temperature": 0, "local_num_predict": 1, "local_seed": 1, "local_temperature": 0}`
- Threshold: `0.0`
- Stop reason: none

### D2

- Code/base commit: `c7f95426fbeada5a840dcc155a14649b798b3214`
- Dataset SHA-256: `6c1db840e8e2bd49d0be9937169774f48161a961309fbae0e2536dfa320a72f6`
- Prompt / policy: `v2` / `all_cases`
- Settings: `{"chat_max_tokens": 512, "chat_seed": 20260919, "chat_temperature": 0, "local_num_predict": 1, "local_seed": 1, "local_temperature": 0}`
- Threshold: `0.0`
- Stop reason: none

### D3

- Code/base commit: `c7f95426fbeada5a840dcc155a14649b798b3214`
- Dataset SHA-256: `6c1db840e8e2bd49d0be9937169774f48161a961309fbae0e2536dfa320a72f6`
- Prompt / policy: `v2` / `deterministic_first`
- Settings: `{"chat_max_tokens": 512, "chat_seed": 20260919, "chat_temperature": 0, "local_num_predict": 1, "local_seed": 1, "local_temperature": 0}`
- Threshold: `0.0`
- Stop reason: none

### local-incomplete

- Code/base commit: `c7f95426fbeada5a840dcc155a14649b798b3214`
- Dataset SHA-256: `6c1db840e8e2bd49d0be9937169774f48161a961309fbae0e2536dfa320a72f6`
- Prompt / policy: `v1` / `all_cases`
- Settings: `{"chat_max_tokens": 512, "chat_seed": 20260919, "chat_temperature": 0, "local_num_predict": 1, "local_seed": 1, "local_temperature": 0}`
- Threshold: `0.0`
- Stop reason: transport failure; no further automatic dispatch

### calibration-selection

- Code/base commit: `43b014deec0ba87078bf97c50aa5c3ec725ef351`
- Dataset SHA-256: `afb59a9f68c66e1a2bb77c31ac5c6ec19857823573f14597452ab17ce80bfc24`
- Prompt / policy: `v2` / `deterministic_first`
- Settings: `{"chat_max_tokens": 512, "chat_seed": 20260919, "chat_temperature": 0, "local_num_predict": 1, "local_seed": 1, "local_temperature": 0}`
- Threshold: `{"chat": null, "jev": null}`
- Stop reason: none

### heldout

- Code/base commit: `43b014deec0ba87078bf97c50aa5c3ec725ef351`
- Dataset SHA-256: `040f9b98927916c4ed585efd5c1cd1cd10150c8c2488d81f3381a9791c802035`
- Prompt / policy: `v2` / `deterministic_first`
- Settings: `{"chat_max_tokens": 512, "chat_seed": 20260919, "chat_temperature": 0, "local_num_predict": 1, "local_seed": 1, "local_temperature": 0}`
- Threshold: `{"chat": 1.0, "jev": 0.6}`
- Stop reason: none

## Separate mechanism evidence

Memory experiment `memory-v1-mechanism-1` remains separate: 24 unique queries and no live fallback inference. Repeated lookup timings are not additional unique cases.

## What remains unknown

- Actual net end-to-end tokens, downstream task success, and cost per accepted change.
- Complete matched local performance; the resource-selected observed intersection is descriptive only.
- Baseline check runtime and energy/hardware charges.
- Population safety and generalization beyond authored families.

No new model execution, installation, purchase, push or external publication is performed by this generator.
