# Definition freeze and token accounting

`locks.py` binds the protocol, benchmark assets, local engine and execution source files into an experiment definition. It requires explicit resolved model IDs, local model/tokenizer digests, preflight evidence identity and reviewed/provisional label status. This is not a claim that current unresolved prerequisites are satisfied: **no real experiment definition or calibration freeze has been created yet**.

After development, `freeze_definition` creates a new run directory and writes once. `freeze_calibration` requires all three arm bundles, complete answers for the 80 calibration cases, matching model IDs and raw-journal hashes. It computes each threshold using the protocol rule. `start_test` requires these locks and creates a one-shot marker before dispatch. Altered inputs, incomplete answers, changed raw evidence and an attempted second opening fail. An interrupted run needs an audited resume path, which is not yet implemented.

These are scientific sequencing guards, not an authorization mechanism. A live caller must separately check explicit user approval and local resource limits. Metadata attestations alone do not prove that a model resolved, a tokenizer was validated or a human reviewed labels. `runner.py` now connects the locks, fixed request schedule, shared spending reservations and independent raw-body calibration replay. Its integration is tested with fake transports; live backend wiring and evidence verification remain required. See `RUNNER.md`.

`token_accounting.py` accepts measurements from one frozen downstream tokenizer. It verifies exact case coverage and document hashes, requires router-input hashes, subtracts full routing overhead from safely avoided reading, and retains negative savings. It rejects estimates, mixed tokenizer identities, changed guides and repeated primary cases. Machine-check skips are not assigned imaginary guide savings. The final manifest must bind measurements to exact rendered prompts.

No actual tokenizer measurements are available yet. The unit tests use explicitly synthetic counts to verify arithmetic only. A validated tokenizer adapter or exact measurement method is still required before H1 can be evaluated; byte estimates are not a substitute.

Offline checks: `python -B -m unittest -v test_locks test_token_accounting` (10 tests). The initial fixture omissions were corrected; all affected tests then passed.
