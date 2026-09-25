# Aldertrace

> **This is experimental. We haven't validated it for production use.**
> Our results come from a small synthetic study with provisional labels. Zero
> prohibited skips in that study doesn't establish safety on new inputs. We
> haven't shown lower cost for completed tasks. Use supervised, disposable trials
> and keep required checks in place. Interfaces and findings may change.

Before an agent skips a prerequisite, make it show the evidence.

We're testing whether a small routing model can save an agent work without
letting it skip something it still needs to do. Aldertrace compares reading
everything, fixed rules, local scoring, Jev, and a conventional chat model.
The model recommends an action; code checks the evidence before allowing it.

So far, Jev has found more eligible skips in a small synthetic test. But routing
cost more input tokens than the assumed reading it avoided. We haven't shown
that it makes complete coding tasks cheaper.

## What you can use this for

Use Aldertrace to study routing decisions, check that recommendations don't bypass
required evidence, and reproduce failures in recovery or cost accounting. The
code and saved results let you inspect what happened. They don't establish
production safety or lower project costs.

The [Jev skills business review](https://github.com/rustybladerunner/jev-skills#business-review--september-2026)
brings together use cases, Jev and related models, our results, costs, and next
decisions. It keeps this replayable study separate from summaries of later
private trials.

Our [next research questions](https://github.com/rustybladerunner/jev-skills/blob/main/docs/research-review-2026-09.md)
cover changes to context, when to refuse a decision, and whether the work saves
time or money overall. The completed v002 data, thresholds, and code stay frozen.

## Start here

Use an existing Python 3.11+ installation. The offline example and core checks
use the standard library. They need no account, key, model download, or paid call.

```sh
python -B skills/examples/demo.py
python -B -m unittest discover -s skills/examples -v
python -B experiments/v002/reproduce.py --hashes-only
```

The example runs real checks on disposable synthetic files. Of five proposed
skips, it permits one and rejects four. Its assumed token counts also show how
routing can cost more than it saves. Those values teach the accounting; they
don't measure a model.

On Windows, replay the recorded experiment:

```sh
python -B experiments/v002/reproduce.py
python -B -m unittest discover -s study-next -v
```

Full replay currently requires Windows. The portable hash check only verifies
file integrity. The optional tokenizer has a pinned version and isn't bundled
or downloaded by these commands. See [how to reproduce the study](experiments/v002/REPRODUCE.md).

Open [the comparison](experiments/v002/index.html) in a browser, or read the
[report](experiments/v002/REPORT.md) and [failure cases](experiments/v002/reports/v002-test-report/report.json).

<a id="what-the-experiment-found"></a>

## What we found

The held-out set has 80 synthetic cases: 40 eligible skips and 40 prohibited
skips. One agent wrote the labels and another reviewed them provisionally.
Independent human review is still missing.

| Policy after evidence checks | Correct skips among 40 eligible cases | Prohibited skips among 40 prohibited cases |
|---|---:|---:|
| Read everything | 0 | 0 |
| Deterministic rules | 20 | 0 |
| Conventional chat | 20 | 0 |
| Jev | 34 | 0 |

Zero prohibited skips applies to these cases. It isn't a production safety
guarantee. Estimated input tokens saved were **-12,240 tokens** for Jev and
**-24,554** for chat. This estimate subtracts observed routing input from assumed
reading avoided. It doesn't include hidden provider wrappers or downstream work.

The local comparison stopped because of resource contention and remains incomplete.
The [separate memory study](experiments/memory-v1/PROTOCOL.md) tests a retrieval
mechanism; it doesn't establish better task outcomes from memory.

## What to inspect

- **Evidence checks:** a model's recommendation stays separate from the action
  the runner permits. A confident explanation can't replace a current matching check.
- **Recovery and accounting:** reserve budget before dispatch, keep uncertain
  charges, reject conflicting recovery owners, and don't quietly resend interrupted work.
- **Reproduction:** parse saved responses again, verify source and dataset
  identities, and compare the calculated reports with the recorded results.
- **Failures:** keep regressions, negative savings, incomplete runs, and unknown
  measurements visible.

[study-next](study-next/README.md) contains the newer recovery and coordination
code. Its CLI uses simulations only. Passing those tests doesn't mean we've run
another live model comparison.

## Use the workflows

[jev-integrate and jev-hypothesize](skills/README.md) describe how we review
changes and test claims. They include a project-context template and the example
above. You can use them in another Jev project without private Aldertrace notes.
They don't grant permission to execute actions or spend money.

## Evidence, privacy, and source records

This public release is a cleaned export of the recorded study. It isn't a new
experiment. Workstation paths and hardware UUIDs were replaced in metadata, and
dependent hashes were updated. The datasets, prompts, model responses, thresholds,
algorithms, and measured values weren't tuned or replaced. The original evidence
remains private.

[PUBLIC-EXPORT.json](PUBLIC-EXPORT.json) records the original export's source
hashes and transformations. Those hashes check consistency; they don't independently
prove when the experiment ran. The frozen protocol keeps its historical wording.
Use this README for current instructions. Old operator-specific restrictions don't
ask you to start services or run another experiment.

We used AI assistance for coding and review. Follow [CONTRIBUTING.md](CONTRIBUTING.md)
for changes, the [writing guide](https://github.com/rustybladerunner/jev-skills/blob/main/STYLE.md)
for prose, and the [publication checklist](https://github.com/rustybladerunner/jev-skills/blob/main/PUBLICATION.md)
before every public update. Review content and history for secrets and personal
data. A clean automated scan doesn't replace that review.

Jev and Calyx are third-party projects. We don't claim affiliation or endorsement.
The separately supplied Calyx code and tokenizer keep their own licenses. No
model weights or Calyx implementation are bundled here.

MIT licensed. See [LICENSE](LICENSE).
