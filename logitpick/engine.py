"""Score declared options from a Backend's first-token logprobs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .codes import assign_codes
from .mathutil import entropy_confidence, mass_from_logprobs, softmax
from .ollama import Backend, NextToken, TokenAlt
from .prompt import render
from .schema import PickRequest


def _alts_by_token(nt: NextToken) -> dict[str, TokenAlt]:
    # First occurrence wins. Ollama should not duplicate tokens in top_k.
    out: dict[str, TokenAlt] = {}
    for alt in nt.alts:
        out.setdefault(alt.token, alt)
    return out


def score_question(
    state: str,
    instructions: str,
    options: dict[str, str],
    backend: Backend,
    model: str,
) -> dict:
    codes = assign_codes(list(options.keys()))
    prompt = render(state, instructions, options, codes)
    nt = backend.next_token(prompt, model=model)
    by_tok = _alts_by_token(nt)

    found_ids: list[str] = []
    found_lps: list[float] = []
    missing: list[str] = []
    code_logprobs: dict[str, float] = {}
    for oid, code in codes.items():
        alt = by_tok.get(code)
        if alt is None:
            missing.append(oid)
            continue
        found_ids.append(oid)
        found_lps.append(alt.logprob)
        code_logprobs[oid] = alt.logprob

    if not found_ids:
        status = "no_codes_in_topk"
        probabilities: dict[str, float] = {oid: 0.0 for oid in options}
        choice = None
        confidence = 0.0
        mass = 0.0
    else:
        probs = softmax(found_lps)
        probabilities = {oid: 0.0 for oid in options}
        for oid, p in zip(found_ids, probs, strict=True):
            probabilities[oid] = p
        choice = found_ids[probs.index(max(probs))]
        confidence = entropy_confidence(probs)
        mass = mass_from_logprobs(found_lps)
        status = "ok" if not missing else "incomplete_topk"

    eval_ms = None
    if nt.eval_duration_ns is not None:
        eval_ms = round(nt.eval_duration_ns / 1_000_000, 1)

    return {
        "choice": choice,
        "probabilities": probabilities,
        "confidence": round(confidence, 6),
        "mass_on_codes": round(mass, 6),
        "missing_options": missing,
        "status": status,
        "codes": codes,
        "generated_token": nt.generated,
        "eval_ms": eval_ms,
        "eval_count": nt.eval_count,
        "prompt_chars": len(prompt),
    }


def pick(req: PickRequest, backend: Backend) -> dict:
    """Score every question. N questions = N `num_predict=1` generates.

    Calls run concurrently over HTTP so wall clock can drop. That is not
    one-prefill shared-cache: Ollama may still prefill N times.
    `forward_passes` stays N. Do not read elapsed_ms as a model speedup.
    """
    started = time.perf_counter()
    n = len(req.questions)
    raw: dict[str, dict] = {}
    if n == 1:
        q = req.questions[0]
        raw[q.id] = score_question(req.state, q.instructions, q.options, backend, req.model)
    else:
        with ThreadPoolExecutor(max_workers=n) as pool:
            futs = {
                pool.submit(
                    score_question,
                    req.state,
                    q.instructions,
                    q.options,
                    backend,
                    req.model,
                ): q.id
                for q in req.questions
            }
            for fut in as_completed(futs):
                raw[futs[fut]] = fut.result()
    answers = {q.id: raw[q.id] for q in req.questions}
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "model": req.model,
        "backend": "ollama-generate-logprobs",
        "mode": "one_question" if n == 1 else "concurrent_questions",
        "forward_passes": n,
        "elapsed_ms": elapsed_ms,
        "answers": answers,
    }
