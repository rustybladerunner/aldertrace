# Jev skills

Two workflows for making Jev experiments and integrations easier to trust.

- **[jev-integrate](jev-integrate/SKILL.md)** checks a proposed change against the code, evidence and tests already in the project. Keep the useful idea; prove the behavior before adopting it.
- **[jev-hypothesize](jev-hypothesize/SKILL.md)** turns an efficiency claim into a bounded experiment with a baseline, a budget and a result someone else can inspect.

These are instructions for a coding agent. They help organize the work; the
agent and your tools still have to do it. Installing a skill grants no access,
spending allowance or permission to publish.

## Try the example

Python 3.11 or newer is enough. From this directory:

```sh
python -B examples/demo.py
python -B -m unittest discover -s examples -v
```

The example runs a real check on disposable synthetic files. It then compares
five proposed skips with the evidence needed to permit them. One has current
passing proof. The others have stale, failed, mismatched or missing proof.
An explanation saying "the check passed" cannot supply a runner receipt. The
runner constructs the receipt in code; text or a deserialized dictionary is not
accepted as one.

Expected result: five proposed skips, one permitted skip, four rejected skips.
The accounting example also shows why avoiding one read can still cost more
overall: 500 illustrative input tokens avoided minus 600 of routing overhead
leaves **-100**. Those token values are assigned for teaching. No model is called,
no tokenizer is used, and the example is not a Jev performance benchmark.

For **jev-integrate**, the proposed shortcut is accepting every `skip`
recommendation. The example exposes the four failures that shortcut would allow.
For **jev-hypothesize**, the hypothesis is that routing reduces total input.
The same example gives a negative result once overhead is counted.

## Install and use

Copy either named skill folder into the skills directory supported by your agent
host, keeping `SKILL.md` and its `references` folder together. For Codex, select
`$jev-integrate` or `$jev-hypothesize` after the host discovers the installed skill.
Other hosts may need their own import mechanism; cross-host discovery is not claimed.

Then give the agent a concrete request, for example:

> Use jev-integrate to review this proposed routing change against our current
> implementation. Reproduce any claimed regression before changing code.

> Use jev-hypothesize to design a test of whether routing saves total input
> tokens. Start from our existing results and allowance. Do not run paid calls.

Each skill includes a small project-context template. Map it to the records your
project already has. For Aldertrace, use its existing protocol and domain memory.
For a new project, fill in the relevant facts; mark missing facts unknown. Never
invent prior results or turn a missing budget into permission to spend.

## What this does and does not establish

These workflows came from Aldertrace's prerequisite-routing experiments and
failure-recovery work. The runnable example demonstrates the evidence boundary
and accounting arithmetic. It does not measure whether these Markdown skills
improve a coding model, make Jev safe in production, or reduce real task cost.

The work was developed with AI coding and review assistance. Model-generated
agreement is not independent human validation. Contributions should include a
reproduction, the expected outcome, and any new limitation they introduce.

MIT licensed; see [LICENSE](../LICENSE) in Aldertrace, or the collection's root
LICENSE when distributed separately. Jev is a third-party service. This project
does not claim affiliation or endorsement. Mount Jeverest remains a future idea.
