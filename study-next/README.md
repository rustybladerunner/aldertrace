# Version-three study orchestration

This directory adds recoverable orchestration around Aldertrace's unchanged,
frozen version-two instruments. It does not change or rerun the completed v002
evaluation. Its new fixtures and fake responses measure instrument behavior only.

The current CLI executes **simulation only**. Research definition validation and
planning are available, but live CLI execution is closed until a fresh prospective
preflight contract verifies actual request/response evidence, identities and cost
envelopes. A digest-shaped metadata string is insufficient. The existing frozen
live adapter remains in `study-execution/`; local execution remains stopped after
contention. No command here loads a model or obtains credentials.

## Reproduce the instrument checks

Python 3.11+ and the standard library are sufficient. Tests were exercised on
Windows with Python 3.12.14. From this directory:

```powershell
python -B -m unittest discover -v
```

Two optional token-accounting tests use the already installed pinned tokenizer
when `ALDERTRACE_TOKENIZER_ENV` names its environment. Without it they skip;
neither mode installs dependencies or downloads a vocabulary. To independently
replay the completed efficacy evidence, use `experiments/v002/reproduce.py`.

## Small executable demonstration

From the repository root, choose a new output folder outside the checkout:

```powershell
python -B study-next/run.py fixture --output C:/Temp/aldertrace-instrument-demo
python -B study-next/run.py freeze --experiment C:/Temp/aldertrace-instrument-demo/experiment --dataset C:/Temp/aldertrace-instrument-demo/dataset --settings C:/Temp/aldertrace-instrument-demo/settings.json
python -B study-next/run.py run --experiment C:/Temp/aldertrace-instrument-demo/experiment --phase calibration
python -B study-next/run.py run --experiment C:/Temp/aldertrace-instrument-demo/experiment --phase calibration --execute --simulate --approval-reference offline-demo
python -B study-next/run.py freeze-thresholds --experiment C:/Temp/aldertrace-instrument-demo/experiment
python -B study-next/run.py run --experiment C:/Temp/aldertrace-instrument-demo/experiment --phase test --execute --simulate --approval-reference offline-demo
python -B study-next/run.py report --experiment C:/Temp/aldertrace-instrument-demo/experiment --phase test
```

The first `run` prints a plan and creates no phase. The explicit simulated runs
execute six cases per phase, two cloud-shaped fake arms, and three test observations
per case: 12 calibration observations and 36 test observations. Deterministic
executable checks bypass calls; calibration makes six fake requests and test makes
18. Each arm has three safe skips and no unsafe enforced skips in the six primary
fixture cases. These values are programmed fixture outcomes, **not model scores**.
Actual task success and net savings remain unknown.

For a clean pause, add `--stop-after 3` to a new simulated phase; continue using
the same command with `--resume`. A completed resume validates the completion
inventory and dispatches nothing. To classify a genuinely interrupted request,
`--resume --reconcile-reference <recorded-reason>` preserves its reserved charge,
records unknown latency/billing and continues the remaining schedule. It never
resends that request. The tests inject real in-process and subprocess interruptions.

## Evidence and recovery contract

- A frozen definition binds complete phase data, labels, declared available arms,
  resolved models, prompt/policy, source hashes, original campaign path and cap.
  Runs load those inputs themselves; callers cannot substitute a subset.
- One existing campaign ledger supplies the lifetime OS lock and shared allowance.
  Each journal has its own lock plus immutable campaign/plan binding and a separate
  recovery audit. Charges are reserved and flushed before dispatch. New folders
  do not reset the allowance. The demonstration creates only a clearly named
  **SIMULATED** ledger; it never replaces the real campaign ledger.
- Missing files, torn tails, missing final newline, orphan global reservations,
  reservations without requests, cap changes and conflicting writers fail closed.
  This version does not truncate, refund, invent missing requests, silently repair
  delimiter damage, or implement cap amendments. Lowering or raising a frozen cap
  is rejected; a future durable amendment needs its own reviewed design.
- A durable request without a result requires explicit audited classification.
  Its missing duration and billed usage stay unknown. A saved result whose driver
  observation was lost is reused with unknown end-to-end duration. Retries count
  as separate attempts and keep separate reservations and observable token overhead.
- Missing usage, excessive cost, access failure, identity drift and terminal
  transport failure stop further dispatch and halt the campaign. Reconciliation
  does not clear that stop. Invalid answer schemas with otherwise valid usage
  remain observed `review` outcomes; they are not silently dropped or repaired.
- `READY.json` binds phase initialization. Append-only observations and immutable
  summary snapshots preserve earlier states; `summary.json` is only the current
  derived view. `COMPLETE.json` binds the completed inventory. A crash before READY
  or a requestless reservation requires manual evidence review, not automatic resume.
- Threshold finalization independently replays all calibration evidence, requires
  its completion inventory and accepts an identical retry without replacing the
  lock. There are no partial intermediate bundles. Test dispatch additionally
  validates calibration provenance, including recovery audit files.
- Reports reparse raw responses with frozen instruments, preserve raw versus
  enforced actions, repeats, resolved identities, unknowns and tokenizer provenance.
  HTTP serialization is an observable input proxy, not exact provider-side net
  tokens. These hashes establish consistency given trusted source/evidence, not
  protection against an adversary rewriting every file and hash.

The library entry point is `coordinator.run_phase`; it requires an already locked
`CampaignBudget`, exact callable transport coverage and explicit approval. CLI
mutations also hold an experiment operation lock. Library callers must serialize
freeze/finalization operations. Live library wiring is not an authorization and
is not claimed to have been evaluated in this new version.

## Decisions and continuity

Use the current code, tests and recorded evidence as the integration baseline.
The public [skills](../skills/README.md) provide project-context templates;
private domain notes and contributor review archives are not bundled.
