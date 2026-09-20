# Aldertrace

Before an agent skips a prerequisite, make it show the evidence.

Aldertrace tests whether a small router can save an agent work without letting
it skip checks it still needs. It compares reading everything, deterministic
rules, local scoring, Jev and a conventional chat model. The model recommends an
action. A separate layer decides whether the available evidence permits it.

The result so far is useful and mixed. Jev covered more eligible cases in a small
synthetic evaluation. The measured input-accounting proxy was still negative:
routing overhead exceeded the reading avoided. Actual savings on completed
coding tasks remain unknown.

## Start here

You need an existing Python 3.11+ installation. The offline example and core
checks use the standard library. No account, key, model download or paid call
is needed.

```sh
python -B skills/examples/demo.py
python -B -m unittest discover -s skills/examples -v
python -B experiments/v002/reproduce.py --hashes-only
```

The first command runs real checks on disposable synthetic files, then shows
five proposed skips: one permitted and four rejected. It also shows a negative
accounting result. Its recommendations and token values are illustrative;
it does not measure Jev or another model.

On Windows, replay the recorded experiment:

```sh
python -B experiments/v002/reproduce.py
python -B -m unittest discover -s study-next -v
```

Full frozen replay currently requires Windows. Portable hash verification checks
integrity only. The optional tokenizer is separately pinned and is not bundled
or downloaded by these commands. See [reproduction details](experiments/v002/REPRODUCE.md).

Open [the comparison](experiments/v002/index.html) in a browser, or read the
[report](experiments/v002/REPORT.md) and [failure cases](experiments/v002/reports/v002-test-report/report.json).

## What the experiment found

The held-out set contains 80 synthetic cases: 40 eligible skips and 40 prohibited
skips. Labels are agent-authored and provisionally reviewed by a separate agent;
independent human adjudication is still missing.

| Enforced policy | Correct skips among 40 eligible cases | Unsafe skips among 40 prohibited cases |
|---|---:|---:|
| Read everything | 0 | 0 |
| Deterministic rules | 20 | 0 |
| Conventional chat | 20 | 0 |
| Jev | 34 | 0 |

Zero observed unsafe skips is a result on these fixtures, not a production safety
guarantee. The Jev input proxy was **-12,240 tokens** and the chat proxy was
**-24,554**. These count stipulated reading and observable routing input. Hidden
provider wrappers and downstream task execution were not measured.

The local comparison stopped after resource contention and remains incomplete.
The [separate memory study](experiments/memory-v1/PROTOCOL.md) is a retrieval
mechanism experiment; it does not establish task-level memory benefit.

## What is worth inspecting

- **The evidence boundary:** keep a model's recommendation separate from the action the runner allows. A confident explanation cannot replace a current matching check.
- **Recovery and accounting:** reserve before dispatch, retain uncertain charges, reject conflicting recovery owners, and avoid quietly resending interrupted work.
- **Reproduction:** reparse saved responses, verify frozen source and dataset identities, and compare computed reports with the recorded results.
- **Failure reporting:** keep regressions, negative savings, incomplete runs and unknown measurements visible.

[study-next](study-next/README.md) contains the newer recovery/orchestration
instrument. Its CLI is simulation-only. Passing its offline tests does not mean
another live model comparison was run.

## Use the workflows

[jev-integrate and jev-hypothesize](skills/README.md) capture the integration and
experimental practices used here. They include a project-context template and
the standalone example above. They can be used with another Jev project without
private Aldertrace notes. They do not grant execution or spending permissions.

## Evidence, privacy and provenance

This release is a sanitized derivative of the recorded study, not a new
experiment. Workstation paths and hardware UUIDs were replaced in metadata;
dependent hashes were rebound. Datasets, prompts, model responses, thresholds,
source algorithms and measured values were not tuned or replaced. The original
private evidence is preserved. [PUBLIC-EXPORT.json](PUBLIC-EXPORT.json) records
source/export hashes and transformations; its hashes establish consistency,
not independent attestation of when the original experiment happened.

The frozen protocol retains its historical wording. Current public use and
reproduction instructions are here; old operator-specific execution restrictions
are not a request to start services or run a new experiment.

This project was built with AI coding and review assistance. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the checks expected of a change.
Jev and Calyx are third-party projects; no affiliation or endorsement is implied.
The separately supplied Calyx implementation and tokenizer retain their own licenses.
No model weights or Calyx implementation are bundled.

MIT licensed. See [LICENSE](LICENSE).
