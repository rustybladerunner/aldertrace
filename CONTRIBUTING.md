# Contributing

Start with a reproducible problem and the behavior you expect to change.
Include the current commit, a small synthetic case, the command you ran and
the actual result. Keep the scope small enough to review.

For a routing change, show the raw recommendation and the action enforcement
allowed. For an efficiency claim, include routing, retries and rejected
recommendations in the cost. Leave measurements unknown when you do not have them.

The recorded v002 evaluation is frozen. Do not edit its cases, labels, thresholds
or source to make a change pass. New behavior belongs in a new version with fresh
evaluation cases. An offline fixture result is not a live-model result.

Run the relevant offline tests. The default commands in the README make no
provider calls. Do not add automatic model downloads, dependency installs or
live tests to the basic reproduction path. This repository does not supply a
spending allowance; any live run needs its own explicit authorization and ledger.

Use synthetic data in reports and examples. Never include credentials, private
corpus, machine paths, hardware identifiers or raw agent-session transcripts.
Review the files and reachable history before publishing a contribution.

This check is required for every public update, including documentation and
release archives. Follow the [public-content review checklist](https://github.com/rustybladerunner/jev-skills/blob/main/PUBLICATION.md).
Run available secret/privacy scans, review findings before upload, and record
the checked artifact identity and limitations. Automated scanning does not detect
all personal information and does not replace review of examples and metadata.

AI assistance is welcome. State what actually ran, what a reviewer checked,
and what remains untested. A model's approval is one review, not proof of safety.

Owned project code and documentation use the MIT license. Preserve the license
and attribution of any third-party material. No third-party model weights,
tokenizer environment or Calyx implementation are included in this release.
