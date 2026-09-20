# Execution contracts — not yet authorized for inference

This layer imports the seven-asset offline draft in `../study/` and the existing local scoring engine. It does not mutate either. `adapters.py` constructs equivalent semantic inputs and strictly parses responses. `journal.py` takes an injected transport. The fixed-endpoint cloud transport and development-only preflight now exist; `preflight.py` defaults to plan-only and requires explicit execution approval. See `PREFLIGHT.md`. No credential-file loader is provided.

Run all offline execution checks from this folder: `python -B -m unittest discover -v`.
The shared campaign budget and phase orchestrator are now connected and tested with fake
transports. See [RUNNER.md](RUNNER.md) for the reproducible full-sequence check and remaining live prerequisites.

## Frozen-before-test choices proposed

- Direct Jev `jev-1.13.0`, documented version ID.
- Conventional model `openai/gpt-4.1-mini` via OpenRouter, OpenAI provider only, no fallbacks, temperature 0, seed 20260919, strict JSON schema, 512 maximum output tokens. Resolve and freeze the actual returned model ID at preflight. If the provider rejects a required setting, record the failure and revise before calibration; do not silently drop it mid-evaluation.
- Local existing logitpick engine, installed `llama3.2:latest`, digest `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`. Verify digest before a run; changing a tag invalidates the run.
- OpenRouter Jev is replication only: request `typesafe/jev-1.13`, freeze its resolved version separately. Prespecify 20 test cases, five per family, using the same label-blind selection as the repeat subset.
- 240 unique cases per main arm, plus 40 extra responses for three total observations on the 20-case subset. At most ten additional development/preflight requests per arm. No preflight on calibration/test cases.
- Single sequential requests; rotate main-arm order deterministically. Complete development first, then freeze requests/settings. Calibrate each arm once and freeze thresholds before test. `runner.py` connects these phase guards and raw calibration replay; its transport integration has only been exercised with fake responses.
- Full four-option probabilities with finite values, sum tolerance 1e-6, and an argmax choice. No silent normalization or JSON repair. Jev confidence, local entropy concentration and chat self-reported correctness remain differently named signals; maximum probability is recorded separately.
- Maximum one retry for explicit transient HTTP responses. Timeout is uncertain billing and is not retried. Authentication/schema errors are not retried. Durable reservation precedes dispatch; raw invalid responses remain replayable. A crash leaves an unresolved attempt, never permission to resend automatically.

## Execution request and conservative cost envelope

Approval remains pending. No cloud or local-model calls have been made by this layer.

Proposed aggregate cloud cap: **US $2**, covering this initial routing comparison and its small Jev transport replication only. No automatic recharge or purchase. Existing TypeSafe credit may cover its share; do not assume the displayed account balance is unchanged.

Observed maximum serialized payloads: Jev 1,453 bytes, replication 1,460, chat 2,605, local 1,441. Budget estimation uses **5,000 input tokens per attempt**, not bytes/4 and not a measured tokenizer count. This is a conservative planning allowance for these short ASCII requests, including interface overhead; preflight must verify actual usage and stop if the allowance is exceeded. This does not establish a token-saving result.

Price snapshot, 2026-09-19: [Jev](https://docs.typesafe.ai/models) $0.042/M input, output free; [GPT-4.1 mini](https://openrouter.ai/openai/gpt-4.1-mini) $0.40/M input, $1.60/M output. OpenRouter replication rate must be rechecked before execution; the initial smoke had an effective $0.042/M input rate.

| Arm | Maximum attempts including preflight and one retry | Reservation per attempt | Total reserved |
| --- | ---: | ---: | ---: |
| Chat | 580 | $0.003 | $1.740 |
| Direct Jev | 580 | $0.00025 | $0.145 |
| OpenRouter Jev replication | 60 | $0.00025 | $0.015 |
| Total | 1,220 | | **$1.900** |

At those prices and planning token allowances, computed cost is approximately $1.77 at the maximum attempt count; reservations leave margin under the $2 cap. Normal no-retry usage should cost less. This is an estimate, not a provider-enforced billing guarantee. Stop before another request if actual usage, prices or reported charges exceed the envelope; retain uncertain attempts at full reservation. A live wrapper must enforce usage/rate validation before running this plan.

Local proposal: up to 290 short llama3.2 requests, one at a time, maximum one hour wall time. Installed model file is 2.02 GB; allow roughly 4–5 GB VRAM and 4–6 GB RAM including runtime/context overhead (estimates, not measured load). Inventory found an RTX 3060 Ti with 8 GB VRAM and 5.5 GB free, no loaded Ollama models. RAM inventory was unavailable due OS read permission. Record cold load and warm timings separately; stop if resource contention appears. Do not download models, evict another session's model, or restart services.

## Still required before credible results

Human label and near-duplicate review (otherwise explicitly provisional), final combined manifest including engine/protocol/config, actual-model preflight, execution locks, live transport/usage recording, downstream tokenizer and adapter-overhead measurement, calibration, held-out inference, offline analysis/failure gallery, separate memory ablations and conditional agent-task pilot.

No compatible standalone tokenizer is installed in the inspected Python runtime. Token-saving claims must remain unmeasured until a tokenizer or documented measurement method is approved and fixed. Any dependency installation requires separate authorization. This execution budget excludes the agent-task pilot.
