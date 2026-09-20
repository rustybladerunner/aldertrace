# Aldertrace synthetic benchmark v2 — provisional

This is a new dataset version. It neither edits nor invalidates the integrity
snapshot of `../study/`. The original dataset remains useful for development and
instrument tests, but its executable generator reused one error-variant suite
across splits. V2 replaces that suite with separately authored domain scenarios.

There are 240 synthetic cases: 12 whole families, 20 cases per family, and four
families in each of development, calibration and test. Each split has 40 semantic
and 40 executable cases, with 40 skip-eligible and 40 non-skippable cases. Family
ownership was fixed before writing the scenario rows. No original v1 case, guide
or domain narrative was copied into v2.

## Authorship and independence limits

Each family contains ten distinct domain concepts with two authored
counterfactuals per concept. Both members of a pair stay in that family and split.
The 240 rows are therefore **120 paired concept clusters**, not 240 independent
scenarios. Report family-level results and respect both concept pairing and
family clustering in uncertainty analysis. Four families per split still provide
only exploratory evidence of generalization.

The source files explicitly supply each concept's criterion, explanations,
evidence and label rationale. The builder serializes the common case contract; it
does not apply an error-mutation list to every family. Generic evidence semantics
are necessarily shared across the experiment: a typed current trusted pass must
match command and artifact. Repetition of that enforcement rule is not a claim
that every possible proof topology is novel. Domain narratives, unit meanings
and counterfactual scenes are owned by one split. Identical schema, paired-case
layout and serialization helpers are disclosed common infrastructure.

The author is an agent, without calls to any target backend, external research,
personal corpus or downloaded data. It is the same agent that reviewed v1's
authoring methodology, so that prior review is **not independent review of v2**.
No human review, blinded label adjudication or external near-duplicate review has
occurred. All labels remain `agent_authored_unreviewed`; results are provisional.

The semantic pairs intentionally contain clear supported and unsupported
explanations. They test recognition of stated mechanisms, not the natural
prevalence of errors, a person's competence, task success, production safety or
comprehensive adversarial robustness. The writing may contain author-specific
style cues. A future naturalistic benchmark needs fresh cases and independent
review rather than adapting these held-out cases after seeing model results.

## Adequacy and reading cost

[SEMANTIC_RUBRIC.md](SEMANTIC_RUBRIC.md) defines adequate explanation before
collection. Every semantic concept has its own substantive prerequisite guide,
shared only by its paired cases. A case does not claim to avoid a large chapter
covering unrelated prerequisites. Brief guides can make model-routing overhead
larger than reading the guide; report that negative result if measured.

Executable documents describe the check, and the existing evaluator assigns
no imaginary reading-token savings to skipping execution. No labels, reference
guides, rationales, source names, family names or split metadata belong in model
requests. Continue using the frozen evaluator's allowlisted public state.

## Reproduce without inference

Python 3.11+ standard library is sufficient. From this directory:

```sh
python -B build.py check
python -B verify.py --evaluator ../study/core.py
python -B integrity.py verify
```

`verify.py` prints aggregate counts and hashes only. It regenerates all cases from
their sources in memory, checks family/concept scope and balance, tests executable
labels against the unchanged evaluator contract, and compares four-word shingles
of scenario criteria and explanations across splits. Schema, paths, IDs and the
common typed-proof sentence are excluded from lexical comparison. The screen
flags Jaccard similarity at least 0.45 or smaller-set containment at least 0.75.
These thresholds are an authoring screen chosen before inference, not calibrated
semantic similarity thresholds or evidence that no conceptual overlap exists.

`validation.json` records the aggregate pre-inference validation. No inference
outputs are stored here. `MANIFEST.json` binds every new dataset file, source,
rubric and verification script; it is a dataset integrity snapshot, not a model,
prompt, tokenizer, policy or threshold freeze. Those belong in the experiment's
separate definition locks. Independent review remains unavailable.

`development-integrity.json` fixes development inputs before their first target
backend collection. Calibration and test were completed afterward without access
to development model outputs. Development source files, builder, plan, rubric
and generated development cases were unchanged during that remaining authoring.
The complete dataset manifest must be fixed before calibration collection and
before any held-out evaluation.

The separate `development.json`, `calibration.json` and `test.json` files avoid
opening held-out rows during development inspection. Each can be regenerated in
a fresh copy using `python -B build.py build --split <split>`; the builder refuses
to overwrite an existing case file. Do not delete or regenerate frozen files to
make a check pass. A changed asset or contaminated test set needs a new version.

## Evidence notation in executable sources

Source evidence uses `trust,revision,artifact,command,exit` records separated by
semicolons. `=` means the declared current value for that field; `_` means absent;
`true`, `false`, `null` and integers retain their distinct JSON types. `s:` marks a
literal string, including deliberately malformed string statuses. `-` is an
empty evidence list. A leading `?` records unknown scope. These are explicit
fixture records, not observations from real runners or signatures. Correctness
of real evidence ingestion remains outside this synthetic benchmark.

No cloud calls, local-model loads, dependency installs, repository changes outside
this new directory, commits or pushes were performed by the dataset author.
