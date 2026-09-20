# Evidence Before Autonomy: offline scaffold

See `../EVALUATION_PROTOCOL.md`. This directory does not modify the existing logitpick engine and never imports a network client. No models have been run on this benchmark. Authoring labels are provisional until independent review.

Run from this directory with an existing Python 3.11+ interpreter (stdlib only):

```
python run.py validate
python -m unittest -v test_core
python run.py baseline
python run.py manifest
python run.py verify
```

`build_cases.py` is the reproducible authoring source. It refuses to overwrite `cases.json`. To check generation, import `build` and compare its returned value with the saved JSON, or generate into a separate temporary copy. Never overwrite an evaluated dataset.

The baseline command reads only development cases for scoring. Test/calibration cases are structurally validated but are not evaluated. The manifest is explicitly an **offline draft integrity snapshot**, not permission to open held-out model evaluation. It refuses silent replacement and detects new, removed, or altered study assets. Results and Python caches are excluded from the asset manifest; inference results must later carry their own run manifest.

Families are assigned before variants. Schema and machine-proof binding rules necessarily repeat across splits; domain narratives do not. Structural checks prove family assignment, counts and exact uniqueness, not semantic novelty. Human near-duplicate review is pending. Templates and labels are visible to the benchmark author; no independent blinded evaluation claim is made.

Model requests are built from an allowlisted state. Labels, rationales, authoring variants, family/split names and full guide documents are not sent. Instructions explicitly identify evidence text as data. Synthetic runner provenance is assumed by fixtures; real signed evidence ingestion is outside this offline scaffold.

The read-everything baseline always reads/runs; deterministic-only skips machine-verified evidence and otherwise reads semantic guides. Model-answer validation rejects nonfinite numbers, missing probabilities, wrong argmax and incomplete top-k. Hybrid enforcement is scored separately from raw recommendations. Confidence is used for semantic-skip eligibility only; no calibration claim is implied.

Document bytes are counted only for safely skipped reading units. Tokens and H1 remain **unmeasured** until a downstream tokenizer and measured adapter overhead are frozen. Do not substitute bytes/4 or claim that avoiding a check necessarily saves a document's tokens.

## Remaining work

- Human label/near-duplicate review and adjudication record.
- Conventional model selection, tokenizer choice, local resource and cloud budget approval.
- Matched adapters, raw-output validation/recording, calibration freeze and evaluation lock.
- Held-out model evaluation, repetitions, metrics/plots and failure gallery.
- Paired agent-task pilot subject to protocol advancement criteria.
- Independent Calyx release review and isolated memory ablations.

The study is not complete because these offline checks pass. A failed efficacy result is valid; missing comparisons are missing evidence.
