"""Choosing the next pair of stops to compare."""

import random
from itertools import combinations

# Above this many stops, unjudged pairs are drawn at random instead of listed.
ENUMERATE_LIMIT = 2000


def next_pair(stop_ids: list[str], judged: set[tuple[str, str]], rng: random.Random,
              enumerate_limit: int = ENUMERATE_LIMIT) -> tuple[str, str] | None:
    """A random pair not judged yet, in random left/right order; None when all are."""
    if len(stop_ids) < 2:
        return None
    ids = sorted(stop_ids)
    if len(ids) <= enumerate_limit:
        open_pairs = [p for p in combinations(ids, 2) if p not in judged]
        if not open_pairs:
            return None
        pair = list(rng.choice(open_pairs))
    else:
        # Pairs vastly outnumber judgments here, so rejection sampling ends fast.
        while True:
            a, b = rng.sample(ids, 2)
            if ((a, b) if a < b else (b, a)) not in judged:
                pair = [a, b]
                break
    rng.shuffle(pair)
    return pair[0], pair[1]


def remaining(stop_ids: list[str], judged: set[tuple[str, str]]) -> int:
    """Unordered pairs of the given stops that are not judged yet."""
    ids = set(stop_ids)
    n = len(ids)
    done = sum(1 for a, b in judged if a in ids and b in ids)
    return n * (n - 1) // 2 - done
