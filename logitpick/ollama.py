"""Ollama /api/generate logprobs client. Loopback only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

DEFAULT_HOST = "http://127.0.0.1:11434"
TOP_K = 20


@dataclass(frozen=True)
class TokenAlt:
    token: str
    logprob: float


@dataclass(frozen=True)
class NextToken:
    generated: str
    alts: tuple[TokenAlt, ...]
    eval_count: int | None
    eval_duration_ns: int | None


class Backend(Protocol):
    def next_token(self, prompt: str, *, model: str) -> NextToken: ...


class OllamaError(RuntimeError):
    pass


class OllamaBackend:
    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 180.0, keep_alive: str = "5m") -> None:
        if not host.startswith("http://127.0.0.1") and not host.startswith("http://localhost"):
            raise OllamaError("Ollama host must be loopback")
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive

    def next_token(self, prompt: str, *, model: str) -> NextToken:
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "logprobs": True,
                "top_logprobs": TOP_K,
                "keep_alive": self.keep_alive,
                "options": {
                    "num_predict": 1,
                    "temperature": 0,
                    "seed": 1,
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise OllamaError(f"Ollama unreachable at {self.host}: {e}") from e

        generated = data.get("response")
        rows = data.get("logprobs")
        if not isinstance(generated, str) or not isinstance(rows, list) or not rows:
            raise OllamaError("Ollama response missing response/logprobs — is this ≥0.34?")
        first = rows[0]
        if not isinstance(first, dict):
            raise OllamaError("logprobs[0] is not an object")
        top = first.get("top_logprobs")
        if not isinstance(top, list) or not top:
            raise OllamaError("top_logprobs missing; cannot score options")
        alts: list[TokenAlt] = []
        for item in top:
            if not isinstance(item, dict):
                continue
            tok = item.get("token")
            lp = item.get("logprob")
            if isinstance(tok, str) and isinstance(lp, (int, float)):
                alts.append(TokenAlt(token=tok, logprob=float(lp)))
        if not alts:
            raise OllamaError("no usable top_logprobs entries")
        eval_count = data.get("eval_count") if isinstance(data.get("eval_count"), int) else None
        eval_ns = data.get("eval_duration") if isinstance(data.get("eval_duration"), int) else None
        return NextToken(generated=generated, alts=tuple(alts), eval_count=eval_count, eval_duration_ns=eval_ns)

    def unload(self, model: str) -> None:
        body = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass
