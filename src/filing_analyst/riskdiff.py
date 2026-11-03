"""What changed in Risk Factors since last year's 10-K.

Risk factor sections are long and mostly boilerplate that carries over year to year,
so the useful signal is in what was added, dropped or rewritten. Paragraphs are compared
by Jaccard similarity on word 3-grams, which is robust to small edits like updated years
and dollar amounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .sections import risk_factor_paragraphs

NEW_BELOW = 0.25        # best match under this -> paragraph is new (or removed)
CHANGED_BELOW = 0.70    # between NEW_BELOW and this -> substantially rewritten


def _shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z]+", text.lower())
    return {tuple(words[i:i + n]) for i in range(max(len(words) - n + 1, 1))}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class RiskDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    rewritten: list[tuple[str, str, float]] = field(default_factory=list)  # (new, old, similarity)
    unchanged: int = 0

    @property
    def summary(self) -> str:
        return (f"{len(self.added)} new, {len(self.removed)} removed, "
                f"{len(self.rewritten)} substantially rewritten, {self.unchanged} carried over")


def diff_risk_factors(current: str, prior: str) -> RiskDiff:
    cur = risk_factor_paragraphs(current)
    old = risk_factor_paragraphs(prior)
    cur_sh = [_shingles(p) for p in cur]
    old_sh = [_shingles(p) for p in old]

    out = RiskDiff()
    matched_old = set()
    for p, s in zip(cur, cur_sh):
        scores = [_jaccard(s, o) for o in old_sh]
        best = max(range(len(scores)), key=scores.__getitem__) if scores else -1
        score = scores[best] if scores else 0.0
        if score < NEW_BELOW:
            out.added.append(p)
        elif score < CHANGED_BELOW:
            out.rewritten.append((p, old[best], score))
            matched_old.add(best)
        else:
            out.unchanged += 1
            matched_old.add(best)

    for j, (p, s) in enumerate(zip(old, old_sh)):
        if j in matched_old:
            continue
        if max((_jaccard(s, c) for c in cur_sh), default=0.0) < NEW_BELOW:
            out.removed.append(p)
    return out
