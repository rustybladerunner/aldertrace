# Contributing

Show us a problem we can reproduce and the behavior you want to change. Include
the commit, a small synthetic case, the command you ran, and the result. Keep
the change small enough to review.

For routing changes, show both the model's recommendation and the action that
passed the evidence checks. For cost claims, count routing, retries, and rejected
recommendations. If a measurement is missing, say so.

The v002 study is frozen. Don't change its cases, labels, thresholds, or source
to make a new result pass. Put new behavior in a new version with fresh cases.
Passing a synthetic test doesn't establish a live-model result.

Run the affected offline tests. The basic README commands make no provider calls.
Don't add automatic model downloads, package installs, or live tests to that path.
This repo grants no spending allowance. A live run needs explicit authorization
and a budget record.

Before every public update, follow the [privacy checklist](https://github.com/rustybladerunner/jev-skills/blob/main/PUBLICATION.md).
Check files, release archives, and reachable history. Run available scans, review
the findings before upload, and record exactly what was checked and any limits.
Use synthetic examples. Never include credentials, private source material,
machine paths, hardware identifiers, or raw agent conversations. A clean scan
doesn't replace review of the content and metadata.

AI assistance is welcome. Say what ran, what was reviewed, and what remains
untested. A model's approval is one review, not proof of safety. Use the
[writing guide](https://github.com/rustybladerunner/jev-skills/blob/main/STYLE.md)
for clear explanations that keep those distinctions intact.

Our code and documentation use the MIT license. Keep third-party licenses and
attribution. This release doesn't include third-party model weights, a tokenizer
environment, or the Calyx implementation.
