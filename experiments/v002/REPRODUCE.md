# Reproduce experiment v002 offline

Run these commands from the Aldertrace repository root using an existing Python
installation. This helper makes no model calls, starts no worker, installs
nothing, and does not write evidence. Its default replay uses only the standard
library. The checkout must include the committed synthetic evidence export.

```powershell
python -B experiments/v002/reproduce.py
```

Full replay currently requires Windows; the project minimum is Python 3.11, and this replay was tested with Python 3.12.14. It verifies all
95 files in `experiments/v002/EXPORT-MANIFEST.json`, the original seven study
assets (including the frozen evaluator), all 24 study-v2 assets, and all 57 frozen
implementation assets. It then calls `experiment_v2.verify` and independently
reparses raw journals through `development_report.report` for the three cloud
development runs, the interrupted local development run, calibration, and test.

The recomputed reports must match their saved reports, including raw and enforced
decisions, family metrics, paired differences, uncertainty, native usage and cost,
latency, retries, and repeat stability. Per-case observations and failure details
are compared internally; stdout contains aggregate counts and metrics only.
Cached summary decisions and usage are not accepted as measured outcomes. Saved
driver timing and run identities remain inputs and are checked against journals.

A successful replay reports six matching reports: five complete and one
incomplete local report. Local unavailability, missing usage, and unknown
measurements remain explicit. A mismatch returns a nonzero exit status. The
helper rechecks file hashes after replay and blocks Python-audited filesystem
writes, socket activity, and process dispatch as protection against accidental
side effects; this guard is not a sandbox for malicious Python/native code.

Portable integrity verification, without importing replay code or recalculating
metrics, is available separately:

```powershell
python -B experiments/v002/reproduce.py --hashes-only
```

To also recompute the serialized input-token proxy, supply an **already present**
environment matching `experiments/v002/tokenizer/tokenizer-manifest.json`:

```powershell
python -B experiments/v002/reproduce.py --tokenizer-environment "C:\path\to\existing\tokenizer-env"
```

That optional environment is pinned to tiktoken 0.14.0, o200k_base, and its exact
manifest, vocabulary, wheel and installed-module hashes. Its native binary
requires CPython 3.12 on Windows amd64. The helper does not create or download this
environment. Without it, input-proxy report bytes are hash-verified but their
token counts are **not recomputed**. With it, counts, provenance identities, and
all input-proxy metrics must match; only the runtime Python patch-version string
is excluded from report equality. The original environment provenance stays
preserved in the saved report.

The frozen threshold journal inventory contains Windows backslash paths. The
original verifier interprets those literally, so full phase replay on POSIX is
unsupported. The helper diagnoses that limitation rather than altering paths,
threshold bytes, or the evaluator to obtain a passing result. A portable future
runner would need a separately versioned change. Hash-only verification is
portable; full replay has been tested on Windows in the original checkout and a
fresh relocated export, both with and without the existing frozen tokenizer.

This reproduces recorded synthetic evidence and arithmetic. It does not establish
independent label correctness, production safety, calibrated probabilities,
statistical significance, full-task success, or actual downstream token savings.
Labels remain agent-authored, with provisional separate-agent review and no human adjudication. Hidden provider wrappers,
baseline execution latency, and actual end-to-end net token savings remain
unknown; the observable input proxy cannot establish the token-reduction target.
The export manifest provides consistency, not independent cryptographic
authenticity; use a trusted checkout/commit when checking provenance.
