# Observable token measurements

`measured_tokens.py` provides real, offline `o200k_base` counts of guide text,
complete public request serializations, reconstructed local-engine prompts, and
observed generated text. **These measurements do not establish H1.** Cloud APIs
do not expose their complete internal prompt construction; Ollama may apply a
model chat template around the observed local prompt. No hidden wrapper is
invented or assigned zero tokens.

The existing strict `token_accounting.py` has not been relaxed. New measurements
use `status=measured_observable_input_proxy` and `h1_eligible=false`; they must not
be relabeled `measured` to bypass its stronger requirement.

## Frozen installation

The operator authorized an isolated tokenizer installation, including vocabulary,
on 2026-09-20. The environment is outside the repository at the active task's
`tokenizer-env/` directory. No model weights or global packages were installed.
Its `site/`, `wheels/`, `cache/`, `install-report.json`, and
`tokenizer-manifest.json` are the reproducibility artifacts. The cache contains
only the tokenizer vocabulary; model execution is unnecessary.

Official [PyPI metadata](https://pypi.org/pypi/tiktoken/0.14.0/json) supplied the
version and wheel hashes. Every downloaded wheel was checked against the matching
official distribution record. OpenAI's
[model mapping](https://github.com/openai/tiktoken/blob/0.14.0/tiktoken/model.py)
maps GPT-4.1 to `o200k_base`; its
[encoding constructor](https://github.com/openai/tiktoken/blob/0.14.0/tiktoken_ext/openai_public.py)
specifies the vocabulary URL and expected digest.

| Asset | Pinned value |
| --- | --- |
| Python / platform | 3.12.14 / Windows AMD64 |
| tiktoken | 0.14.0 |
| Encoding | o200k_base |
| Manifest SHA-256 | `84f40a9953de9923f546e700c2a36b8074337823dc51d6fe83cbb6849652f477` |
| tiktoken wheel SHA-256 | `087538c080e5ff421abd3a0785ed63c5111d06af98e6cd0d374dbe5969147ca3` |
| Native tokenizer module SHA-256 | `4819f4517aa091644f574d607a8d2308b9700dcccd1708397951fa94abbe8697` |
| Vocabulary SHA-256 | `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d` |

The manifest additionally binds all 97 installed Python/native modules, seven
wheels, the exact tokenization regex and special-token mapping. Dependencies are
regex 2026.9.10, requests 2.34.2, charset-normalizer 3.5.1, idna 3.20, urllib3 2.8.0,
and certifi 2026.7.22. The recorded wheel collection supports offline installation
with `pip --no-index --find-links ... --target ...`; do not silently substitute
versions or use this document as fresh installation authorization. Another
platform requires a new documented environment manifest and explicit identity.

At runtime `FrozenTokenizer` checks the manifest, module inventory, module hashes,
wheel hashes and vocabulary hash before importing the isolated package. It builds
the encoding directly from the local vocabulary, avoiding plugin discovery and
automatic downloads. `encode_ordinary` treats special-token-looking text as
ordinary text. Known validation: `hello world` produces IDs `[24912, 2375]`.
The manifest's recorded Python version and current runtime version remain visible.

## What each number means

- **Guide tokens:** exact UTF-8 document text encoded with the common tokenizer.
  A verified executable check never receives invented reading-token savings.
- **Cloud input proxy:** the entire canonical HTTP JSON body, including system
  and user messages, criteria/options, instructions, output schema, model fields,
  provider restrictions and generation settings. This serialization includes
  fields a provider might not tokenize and cannot reveal fields it adds internally.
- **Local input proxy:** each complete prompt reconstructed by the unchanged
  `logitpick` renderer, including its fixed instruction, question, options, state
  and answer suffix. Prompt/source hashes are recorded. The canonical local
  adapter JSON count is also reported as a separate diagnostic.
- **Output:** actual chat message text or the local generated token is counted
  separately when observed, including invalid/incomplete answers. Jev's structured
  decision JSON is not assumed to be a generated token sequence. HTTP response
  serialization has its own diagnostic count and never substitutes for generation.
- **Provider-native usage:** reported input/output counts stay separate from the
  common-tokenizer measurements. Local native usage remains in the local telemetry
  journal; it is not guessed from a normalized decision response.
- **Retries/failures:** every recorded request attempt contributes observable
  input overhead, whether successful, invalid, rejected, failed or interrupted.
  This is a conservative attempted-input proxy; dispatch or server consumption
  cannot always be proven. Missing output/native usage stays null. Reservations
  without a request are flagged separately and cannot support a complete total.

Input-only net proxy = safely avoided mandatory guide tokens minus all recorded
attempt input proxies. Output-inclusive net proxy additionally subtracts observed
generated output only when every attempt has that measurement. Missing output
makes the output-inclusive total unknown. Retain negative savings. Count repeat
trials separately; their retries belong to their own logical request. Never pool
three repeat trials against one guide-loading opportunity.

## Offline reproduction and integration

Use the environment path explicitly; no persistent environment changes are needed:

```powershell
$env:ALDERTRACE_TOKENIZER_ENV = '<approved task directory>\tokenizer-env'
python -B -m unittest -v test_measured_tokens
python -B measured_tokens.py --environment $env:ALDERTRACE_TOKENIZER_ENV `
  --journal '<run directory>\chat.jsonl' --journal '<run directory>\jev.jsonl' `
  --output '<new path>\token-measurements.json'
```

The bundled Windows Python and sandbox account own the isolated installation;
run the offline measurement command in that same account/context. Network
elevation is unnecessary for reproduction.

For the case-level report:

```python
tokenizer = FrozenTokenizer(environment_path)
journal = measure_journal(tokenizer, journal_path)
attempts = [a for a in journal['attempts'] if a['key'] == logical_request_key]
measurement = measure_case(tokenizer, case, attempts)
report = summarize(cases, predictions_by_case, measurements_by_case, tokenizer.identity)
```

Use an empty attempt list only for a genuinely undispatched deterministic action.
Inspect `reserved_without_request` before asserting complete accounting. Bind the
dataset, run-definition, journal, tokenizer manifest and returned measurement
module hashes in the experiment log. Each text measurement also records its exact
text hash, byte count and token-ID-list hash. This enables reproducible proxy
comparisons while leaving actual net agent-token savings unknown.

Validation comprises nine synthetic plumbing tests and four tests against the
installed tokenizer. The latter explicitly disable socket connection attempts.
Tests cover full schema/instruction inclusion, retries, missing measurements,
changed guides, mixed tokenizers, repeat separation, executable-check savings,
known token IDs and asset drift. Tests are simulated instrumentation evidence,
not routing efficacy results.
