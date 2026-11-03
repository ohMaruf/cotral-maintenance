"""What the models are asked and how to name it: categories and models, in display order."""

from dataclasses import dataclass
from typing import Literal

from cotral_maintenance.scoring import QUESTIONS, VIEW_ROLES

CategoryKind = Literal["level", "probability"]


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
    "classifiable": "Sign visible",
}


def _category(key: str) -> Category:
    question = QUESTIONS[key]
    kind: CategoryKind = "probability" if question["type"] == "noul" else "level"
    return Category(key, _LABELS.get(key, key.replace("_", " ").capitalize()), kind, question["instructions"])


CATEGORIES = [_category(key) for key in QUESTIONS]
CATEGORY_KEYS = [c.key for c in CATEGORIES]

MODELS = [
    Model("clef", "Clef", "Probability-weighted expected level"),
    Model("gemma", "Gemma", "Integer level, structured tool call"),
]


def models_for(keys: list[str]) -> list[Model]:
    """The known models first, in display order, then any other configured model."""
    known = {m.key: m for m in MODELS}
    return [known[k] for k in known if k in keys] + [Model(k, k.capitalize(), "") for k in keys if k not in known]


def photo_description(view: str) -> str:
    """"About 24 m before the mapped stop position" for sweep_1; the view name otherwise."""
    role = VIEW_ROLES.get(view)
    if role is None:
        return view.replace("_", " ").capitalize()
    where = role.split(", ", 1)[1].rsplit(" along the road", 1)[0]
    return where[0].upper() + where[1:]

