"""Request validation. Fail closed, name the field."""

from __future__ import annotations

from dataclasses import dataclass

from .codes import MAX_OPTIONS, MIN_OPTIONS

MAX_STATE_CHARS = 8000
MAX_INSTRUCTIONS_CHARS = 500
MAX_OPTION_DESC_CHARS = 300
MAX_QUESTIONS = 8
MAX_OPTION_ID_CHARS = 64


class PickError(ValueError):
    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def as_dict(self) -> dict:
        body = {"code": self.code, "message": self.message}
        if self.field:
            body["field"] = self.field
        return body


@dataclass
class Question:
    id: str
    instructions: str
    options: dict[str, str]


@dataclass
class PickRequest:
    state: str
    questions: list[Question]
    model: str = "llama3.2"


def parse_request(raw: dict) -> PickRequest:
    if not isinstance(raw, dict):
        raise PickError("malformed", "body must be a JSON object")
    state = raw.get("state")
    if not isinstance(state, str) or not state.strip():
        raise PickError("invalid_state", "state must be a non-empty string", "state")
    if len(state) > MAX_STATE_CHARS:
        raise PickError("state_too_long", f"state exceeds {MAX_STATE_CHARS} chars", "state")

    model = raw.get("model", "llama3.2")
    if not isinstance(model, str) or not model.strip() or "/" in model or "\\" in model:
        raise PickError("invalid_model", "model must be a local Ollama tag", "model")

    qraw = raw.get("questions")
    if not isinstance(qraw, dict) or not qraw:
        raise PickError("invalid_questions", "questions must be a non-empty object", "questions")
    if len(qraw) > MAX_QUESTIONS:
        raise PickError("too_many_questions", f"max {MAX_QUESTIONS} questions", "questions")

    questions: list[Question] = []
    for qid, spec in qraw.items():
        if not isinstance(qid, str) or not qid.strip():
            raise PickError("invalid_question_id", "question ids must be non-empty strings", "questions")
        if not isinstance(spec, dict):
            raise PickError("invalid_question", f"question {qid!r} must be an object", qid)
        instructions = spec.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise PickError("invalid_instructions", "instructions must be a non-empty string", f"{qid}.instructions")
        if len(instructions) > MAX_INSTRUCTIONS_CHARS:
            raise PickError("instructions_too_long", f"max {MAX_INSTRUCTIONS_CHARS} chars", f"{qid}.instructions")
        options = spec.get("options")
        if not isinstance(options, dict):
            raise PickError("invalid_options", "options must be an object", f"{qid}.options")
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            raise PickError(
                "bad_option_count",
                f"need {MIN_OPTIONS}–{MAX_OPTIONS} options, got {len(options)}",
                f"{qid}.options",
            )
        cleaned: dict[str, str] = {}
        for oid, desc in options.items():
            if not isinstance(oid, str) or not oid.strip() or len(oid) > MAX_OPTION_ID_CHARS:
                raise PickError("invalid_option_id", "option ids must be short non-empty strings", f"{qid}.options")
            if oid.strip() != oid:
                raise PickError("invalid_option_id", "option ids cannot have surrounding whitespace", f"{qid}.options")
            if not isinstance(desc, str):
                raise PickError("invalid_option_desc", "option descriptions must be strings", f"{qid}.options.{oid}")
            if len(desc) > MAX_OPTION_DESC_CHARS:
                raise PickError("option_desc_too_long", f"max {MAX_OPTION_DESC_CHARS} chars", f"{qid}.options.{oid}")
            cleaned[oid] = desc
        questions.append(Question(id=qid, instructions=instructions.strip(), options=cleaned))

    return PickRequest(state=state, questions=questions, model=model.strip())
