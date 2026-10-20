"""
settle.py - stop asking once the answer is settled.

A test does not need every simulated person to answer once its estimates are tight. People are asked in a random
order interleaved across cells (by default one cell per model provider, so every provider stays equally represented
at every point), and after each batch every cell's would-convert shares (yes / maybe / no) get a Wilson range. A cell
is settled when it has at least `min_n` answers and the widest of its three ranges is within +/- `margin` points;
settled cells are not asked again, and asking ends when every cell is settled or everyone has been asked.

Looking at the results after every batch and stopping when they look tight makes a plain 95% range too optimistic,
so the stopping check uses z = 2.5 (a common allowance for about ten interim looks); the ranges reported with the
results are the usual 95% ones. Stdlib only.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, Iterable, List, Optional

Z_STOP = 2.5


def half_width(k: float, n: int, z: float = Z_STOP) -> float:
    """Half the width of the Wilson range for k of n, in percentage points (100 when n is 0)."""
    if n <= 0:
        return 100.0
    p = k / n
    d = 1 + z * z / n
    return 100 * z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d


def interleaved_order(people: List[Any], cell_of: Callable[[Any], str], seed: int = 11) -> List[Any]:
    """Everyone, shuffled within their cell, then dealt round-robin across cells (largest cells first)."""
    rng = random.Random(seed)
    cells: Dict[str, List[Any]] = {}
    for p in people:
        cells.setdefault(cell_of(p), []).append(p)
    for v in cells.values():
        rng.shuffle(v)
    queues = sorted(cells.values(), key=len, reverse=True)
    out: List[Any] = []
    for i in range(max((len(q) for q in queues), default=0)):
        for q in queues:
            if i < len(q):
                out.append(q[i])
    return out


def cell_status(answers: Iterable[Dict[str, Any]], margin: float, min_n: int, z: float = Z_STOP) -> Dict[str, Any]:
    """answers: {"cell", "yes", "maybe", "no"} per answered person (each 0/1). Per cell: n, the widest half-width
    and whether it is settled."""
    tally: Dict[str, Dict[str, float]] = {}
    for a in answers:
        t = tally.setdefault(a["cell"], {"n": 0, "yes": 0.0, "maybe": 0.0, "no": 0.0})
        t["n"] += 1
        for k in ("yes", "maybe", "no"):
            t[k] += float(a.get(k) or 0)
    out = {}
    for cell, t in tally.items():
        n = int(t["n"])
        widest = max(half_width(t[k], n, z) for k in ("yes", "maybe", "no"))
        out[cell] = {"n": n, "half_width": round(widest, 1), "settled": n >= min_n and widest <= margin}
    return out


class Settler:
    """Feeds batches to a test and stops asking a cell once it is settled."""

    def __init__(self, people: List[Any], cell_of: Callable[[Any], str], margin: float = 5.0, min_n: int = 60,
                 seed: int = 11, z: float = Z_STOP):
        self.cell_of = cell_of
        self.margin, self.min_n, self.z = float(margin), int(min_n), float(z)
        self.queue = interleaved_order(people, cell_of, seed)
        self.cells = sorted({cell_of(p) for p in people})
        self.answers: List[Dict[str, Any]] = []
        self.asked: Dict[str, int] = {c: 0 for c in self.cells}
        self.status: Dict[str, Any] = {}

    def next_batch(self, size: int) -> List[Any]:
        settled = {c for c, s in self.status.items() if s["settled"]}
        batch, rest = [], []
        for p in self.queue:
            if len(batch) < size and self.cell_of(p) not in settled:
                batch.append(p)
            elif self.cell_of(p) not in settled:
                rest.append(p)
        self.queue = rest
        for p in batch:
            self.asked[self.cell_of(p)] += 1
        return batch

    def record(self, person: Any, yes: float, maybe: float, no: float) -> None:
        self.answers.append({"cell": self.cell_of(person), "yes": yes, "maybe": maybe, "no": no})

    def update(self) -> Dict[str, Any]:
        self.status = cell_status(self.answers, self.margin, self.min_n, self.z)
        return self.status

    @property
    def done(self) -> bool:
        return not self.queue or (bool(self.status) and all(self.status.get(c, {}).get("settled") for c in self.cells))

    def summary(self, total_people: int) -> Dict[str, Any]:
        asked = sum(self.asked.values())
        return {"rule": f"stop a cell at >= {self.min_n} answers and every would-convert share within "
                        f"+/-{self.margin:g} points (z = {self.z:g} for repeated looks)",
                "margin": self.margin, "min_n": self.min_n, "z": self.z, "people": total_people, "asked": asked,
                "not_asked": total_people - asked,
                "cells": {c: {**self.status.get(c, {"n": 0, "half_width": 100.0, "settled": False}), "asked": self.asked[c]}
                          for c in self.cells}}
