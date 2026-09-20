# Development preflight

`python -B preflight.py` is plan-only: it verifies the original draft manifest and makes zero calls. This mode was run and confirmed. Importing transport code does not access credentials or send a request.

After explicit operator approval, execution requires `--execute`, a new `--output` directory, an `--approval-reference`, and `--campaign` pointing to the shared study budget ledger. Use `--create-campaign` only for the first ledger; subsequent runs must reuse that ledger without the flag. The reference must point to actual consent; supplying text is not consent. Keys must be in the child process environment, never arguments or saved artifacts. No `.env` reader, key copying, installation or billing changes are performed by this command.

The default execution would make one development request for direct Jev and one for the conventional chat arm. Up to ten development cases per arm are supported. These attempts, including retries, consume the existing study allowance; they are not extra budget. The preflight's maximum reservation is $0.065, nested within the proposed $2 aggregate cap. `CampaignBudget` now carries reservations across run directories and process restarts, and rejects concurrent writers. Uncertain attempts retain their reservations.

The driver records requests/attempts before dispatch, records raw redacted responses, and stops on invalid response, unexpected model, missing usage, excessive tokens or a charge exceeding its per-attempt reservation. Response schema/model mismatches must be investigated before any subsequent calls, never repaired during held-out evaluation. HTTP redirects are disabled; endpoints are fixed; request/response sizes and read timeout are bounded.

This preflight covers the two primary cloud arms only. The phase orchestrator and shared accounting are connected and tested with injected fake transports; see `RUNNER.md`. Local backend wiring and OpenRouter/Jev replication remain. No live preflight has been performed by this execution layer, no real model/threshold freeze exists, and approval remains pending.

Offline checks: `python -B -m unittest -v test_transport test_preflight test_budget test_runner`. Tests use fake responses/transports. They validate code behavior, not live provider compatibility.
