"""What the scorer is asked and how to name it: categories and the model, in display order."""

from dataclasses import dataclass
from typing import Literal

from cotral_maintenance.scorer.questions import questions

CategoryKind = Literal["level", "probability"]
MODEL_KEY = "imajev"
MODEL_DESCRIPTION = "Expected level under Imajev's calibrated probabilities"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    kind: CategoryKind
    description: str


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    description: str


_LABELS = {
    "waiting_area": "Waiting area",
    "requires_maintenance": "Overall maintenance",
}


def _category(question) -> Category:
    kind: CategoryKind = "probability" if question.type == "noul" else "level"
    label = _LABELS.get(question.name, question.name.replace("_", " ").capitalize())
    return Category(question.name, label, kind, question.instructions)


CATEGORIES = [_category(q) for q in questions()]
CATEGORY_KEYS = [c.key for c in CATEGORIES]


def model_for(scorer_model: str | None) -> Model:
    return Model(MODEL_KEY, scorer_model or "Imajev", MODEL_DESCRIPTION)


def evidence_text(answer: dict) -> str | None:
    """"unknown 23%, confidence 0.41" from one entry of `scores.answers`; None when it has neither."""
    unknown, confidence = answer.get("unknown_probability"), answer.get("confidence")
    parts = []
    if unknown is not None:
        parts.append(f"unknown {unknown:.0%}")
    if confidence is not None:
        parts.append(f"confidence {confidence:.2f}")
    if not parts:
        return None
    return ("abstained, " if answer.get("abstained") else "") + ", ".join(parts)
