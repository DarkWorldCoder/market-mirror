"""Diagnostics and corrections for a synthetic panel against a small real sample (50-300 answers).

Implements the three checks and the doubly-robust correction of arXiv 2609.13148 ("When can you trust your
synthetic users?") in pure Python:

  1. covariate overlap   ESS/N of density-ratio weights from a domain classifier (real vs synthetic on
                         demographics) and that classifier's AUC;
  2. conditional calibration  beta_g = Cov(Y_real, Y_syn | g) / Var(Y_syn | g) per subgroup, from cell means;
  3. (cross-LLM stability is run by the CLI: two panels, min Spearman rho; see `stability`)

and a verdict per subgroup: trust / correct / walk-away. `correct()` returns the AIPW estimate of a rate
(would-convert, CTR, open rate...) with 5-fold cross-fitting and a standard error.

Rows are dicts: {"segment", "country", "age", "gender", "y"} with y in [0, 1] (yes = 1, maybe = 0.5, no = 0,
or any rate). Real rows come from the user's own survey / ad export / email stats.
"""

import math
import random
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

DIMS = ("segment", "country", "age_band", "gender")


def age_band(age: Any) -> str:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return "?"
    for lo, hi in ((18, 24), (25, 34), (35, 44), (45, 54), (55, 64)):
        if lo <= a <= hi:
            return f"{lo}-{hi}"
    return "65+" if a >= 65 else "<18"


def features(row: Dict[str, Any]) -> Dict[str, float]:
    """One-hot demographics."""
    f: Dict[str, float] = {"bias": 1.0}
    for dim in DIMS:
        v = row.get(dim) if dim != "age_band" else (row.get("age_band") or age_band(row.get("age")))
        if v not in (None, ""):
            f[f"{dim}={str(v).strip().lower()}"] = 1.0
    return f


def logistic_fit(xs: List[Dict[str, float]], ys: List[float], steps: int = 300, lr: float = 0.5, l2: float = 0.01) -> Dict[str, float]:
    """Tiny L2-regularised logistic regression by gradient descent (features are sparse one-hots)."""
    w: Dict[str, float] = defaultdict(float)
    n = max(1, len(xs))
    for _ in range(steps):
        grad: Dict[str, float] = defaultdict(float)
        for x, y in zip(xs, ys):
            z = sum(w[k] * v for k, v in x.items())
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            for k, v in x.items():
                grad[k] += (p - y) * v
        for k in list(set(list(w) + list(grad))):
            w[k] -= lr * (grad[k] / n + l2 * (w[k] if k != "bias" else 0.0))
    return dict(w)


def predict(w: Dict[str, float], x: Dict[str, float]) -> float:
    z = sum(w.get(k, 0.0) * v for k, v in x.items())
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def auc(scores: Sequence[float], labels: Sequence[float]) -> float:
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return 0.5
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def overlap(synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Domain classifier real(1) vs synthetic(0) on demographics -> AUC, density-ratio weights, ESS/N."""
    xs = [features(r) for r in synthetic] + [features(r) for r in real]
    ys = [0.0] * len(synthetic) + [1.0] * len(real)
    w = logistic_fit(xs, ys)
    scores = [predict(w, x) for x in xs]
    a = auc(scores, ys)
    prior = len(real) / max(1, len(synthetic) + len(real))
    weights = []
    for x in xs[: len(synthetic)]:
        p = min(0.999, max(0.001, predict(w, x)))
        weights.append((p / (1 - p)) * ((1 - prior) / prior))          # odds ratio -> density ratio p_T(x)/p_S(x)
    if weights:
        cap = sorted(weights)[int(0.99 * (len(weights) - 1))]
        weights = [min(v, cap) for v in weights]
        tot = sum(weights)
        weights = [v / tot * len(weights) for v in weights]            # self-normalised, mean 1
    ess = (sum(weights) ** 2 / sum(v * v for v in weights)) if weights else 0.0
    ess_ratio = ess / len(weights) if weights else 0.0
    verdict = "walk-away" if a > 0.95 or ess_ratio < 0.01 else "caution" if ess_ratio < 0.10 else "ok"
    return {"auc": round(a, 3), "ess_ratio": round(ess_ratio, 3), "verdict": verdict, "weights": weights, "model": w}


def _group(rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        v = r.get(key) if key != "age_band" else (r.get("age_band") or age_band(r.get("age")))
        out[str(v or "?")].append(r)
    return out


def conditional_calibration(synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]], key: str = "segment",
                            min_n: int = 5) -> Dict[str, Any]:
    """beta_g from cell means inside each subgroup g (cells = the other demographics): slope of real on synthetic.
    Verdict per subgroup: trust (beta in [0.8, 1.2] and the group mean within 5 points), correct (beta in
    [0.5, 1.5] with the overall sign), walk-away otherwise or with too little real data."""
    gs, gr = _group(synthetic, key), _group(real, key)
    out = {}
    overall = []
    for g in sorted(set(gs) | set(gr)):
        s_rows, r_rows = gs.get(g, []), gr.get(g, [])
        if len(r_rows) < min_n or not s_rows:
            out[g] = {"n_real": len(r_rows), "n_syn": len(s_rows), "verdict": "walk-away", "reason": "too little real data"}
            continue
        # cells inside the subgroup: country x gender (coarse on purpose: small real samples make finer cells noisy);
        # the slope is weighted by the smaller side of each cell
        def cell(r):
            return (str(r.get("country") or ""), str(r.get("gender") or ""))
        cs, cr = defaultdict(list), defaultdict(list)
        for r in s_rows:
            cs[cell(r)].append(float(r["y"]))
        for r in r_rows:
            cr[cell(r)].append(float(r["y"]))
        # a slope needs well-filled cells: at least 20 real answers in each cell it uses (unpaired panels are noisy)
        pairs = [(sum(cs[c]) / len(cs[c]), sum(cr[c]) / len(cr[c]), min(len(cs[c]), len(cr[c]))) for c in cs if c in cr and len(cr[c]) >= 20]
        ms, mr = sum(float(r["y"]) for r in s_rows) / len(s_rows), sum(float(r["y"]) for r in r_rows) / len(r_rows)
        beta = None                                                     # None = the cells do not differ enough to judge a slope
        if len(pairs) >= 3 and (max(x for x, _, _ in pairs) - min(x for x, _, _ in pairs)) >= 0.10:
            wsum = sum(w for _, _, w in pairs)
            mx = sum(x * w for x, _, w in pairs) / wsum
            my = sum(y * w for _, y, w in pairs) / wsum
            var = sum(w * (x - mx) ** 2 for x, _, w in pairs)
            beta = round(sum(w * (x - mx) * (y - my) for x, y, w in pairs) / var, 2) if var > 1e-6 else None
        gap = abs(mr - ms)
        # Verdict on the level gap only. The paper's beta_g uses paired human/twin answers; with unpaired panels
        # the cell slope is reported for information but is too noisy to decide on.
        if gap <= 0.05:
            verdict = "trust"
        elif gap <= 0.25:
            verdict = "correct"
        else:
            verdict = "walk-away"
        out[g] = {"n_real": len(r_rows), "n_syn": len(s_rows), "beta": beta, "mean_syn": round(ms, 3),
                  "mean_real": round(mr, 3), "gap": round(gap, 3), "verdict": verdict, "cells": len(pairs)}
        if beta is not None:
            overall.append(beta)
    return {"by_group": out, "beta_mean": round(sum(overall) / len(overall), 2) if overall else None}


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) != len(b) or len(a) < 3:
        return None

    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 3) if den else None


def stability(panels: List[Dict[str, float]]) -> Dict[str, Any]:
    """panels: [{subgroup: estimate}] from different models/prompts -> min pairwise Spearman rho and a verdict."""
    if len(panels) < 2:
        return {"min_rho": None, "verdict": "unknown", "pairs": 0}
    keys = sorted(set.intersection(*(set(p) for p in panels)))
    rhos = []
    for i in range(len(panels)):
        for j in range(i + 1, len(panels)):
            r = spearman([panels[i][k] for k in keys], [panels[j][k] for k in keys])
            if r is not None:
                rhos.append(r)
    if not rhos:
        return {"min_rho": None, "verdict": "unknown", "pairs": 0}
    m = min(rhos)
    return {"min_rho": m, "verdict": "ok" if m > 0.8 else "caution" if m >= 0.5 else "walk-away", "pairs": len(rhos), "subgroups": len(keys)}


def correct(synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]], folds: int = 5, seed: int = 7) -> Dict[str, Any]:
    """AIPW estimate of the target-population mean of y with K-fold cross-fitting.

    tau = mean(Y_real) + mean_i[ w(X_i) * (Y_i_syn + g(X_i) - mu_T(X_i)) ]  with  g = E[Y_T|x] - E[Y_S|x],
    mu_T = mu_S + g. Nuisances (propensity weights from the domain classifier, cell-mean outcome models) are fit
    on the other folds. Returns estimate, SE, the naive synthetic mean and the real sample mean."""
    if len(real) < 10 or not synthetic:
        return {"estimate": None, "se": None, "reason": "need at least 10 real answers",
                "naive_syn": _mean([r["y"] for r in synthetic]) if synthetic else None,
                "real_mean": _mean([r["y"] for r in real]) if real else None}
    rng = random.Random(seed)
    s_idx = list(range(len(synthetic)))
    r_idx = list(range(len(real)))
    rng.shuffle(s_idx)
    rng.shuffle(r_idx)
    k = max(2, min(folds, len(real) // 5))
    s_folds = [s_idx[i::k] for i in range(k)]
    r_folds = [r_idx[i::k] for i in range(k)]
    fold_scores = []
    for f in range(k):
        s_train = [synthetic[i] for j in range(k) if j != f for i in s_folds[j]]
        r_train = [real[i] for j in range(k) if j != f for i in r_folds[j]]
        s_test = [synthetic[i] for i in s_folds[f]]
        r_test = [real[i] for i in r_folds[f]]
        if not s_train or not r_train or not s_test or not r_test:
            continue
        ov = overlap(s_train, r_train)
        model, prior = ov["model"], len(r_train) / (len(s_train) + len(r_train))
        mu_s = _cell_means(s_train)
        mu_r = _cell_means(r_train)

        def g_hat(r):
            c = _cell(r)
            return mu_r.get(c, mu_r["__all__"]) - mu_s.get(c, mu_s["__all__"])

        def w_hat(r):
            p = min(0.999, max(0.001, predict(model, features(r))))
            return (p / (1 - p)) * ((1 - prior) / prior)
        ws = [w_hat(r) for r in s_test]
        cap = sorted(ws)[int(0.99 * (len(ws) - 1))]
        ws = [min(v, cap) for v in ws]
        tot = sum(ws) or 1.0
        aug = sum((v / tot) * (float(r["y"]) + g_hat(r) - (mu_s.get(_cell(r), mu_s["__all__"]) + g_hat(r)))
                  for v, r in zip(ws, s_test))
        fold_scores.append(_mean([r["y"] for r in r_test]) + aug)
    if not fold_scores:
        return {"estimate": None, "se": None, "reason": "cross-fitting failed"}
    est = sum(fold_scores) / len(fold_scores)
    se = (math.sqrt(sum((x - est) ** 2 for x in fold_scores) / max(1, len(fold_scores) - 1)) / math.sqrt(len(fold_scores))
          if len(fold_scores) > 1 else None)
    return {"estimate": round(est, 4), "se": round(se, 4) if se is not None else None, "folds": len(fold_scores),
            "naive_syn": round(_mean([r["y"] for r in synthetic]), 4), "real_mean": round(_mean([r["y"] for r in real]), 4)}


def _mean(xs: Sequence[float]) -> float:
    xs = [float(x) for x in xs]
    return sum(xs) / len(xs) if xs else 0.0


def _cell(r: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (str(r.get("segment") or ""), str(r.get("country") or ""), str(r.get("gender") or ""),
            r.get("age_band") or age_band(r.get("age")))


def _cell_means(rows: List[Dict[str, Any]]) -> Dict[Any, float]:
    cells: Dict[Any, List[float]] = defaultdict(list)
    for r in rows:
        cells[_cell(r)].append(float(r["y"]))
    out = {c: sum(v) / len(v) for c, v in cells.items()}
    out["__all__"] = _mean([r["y"] for r in rows])
    return out


def diagnose(synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]], key: str = "segment") -> Dict[str, Any]:
    """The full check: overlap, conditional calibration per subgroup, an overall verdict and the AIPW correction."""
    ov = overlap(synthetic, real)
    cal = conditional_calibration(synthetic, real, key)
    verdicts = [v.get("verdict") for v in cal["by_group"].values()]
    if ov["verdict"] == "walk-away":
        overall = "walk-away"
    elif verdicts and all(v == "trust" for v in verdicts):
        overall = "trust"
    elif verdicts and any(v == "walk-away" for v in verdicts):
        overall = "mixed"
    else:
        overall = "correct"
    corr = correct(synthetic, real)
    return {"n_synthetic": len(synthetic), "n_real": len(real), "overlap": {k: v for k, v in ov.items() if k not in ("weights", "model")},
            "calibration": cal, "verdict": overall, "corrected": corr,
            "reading": {"trust": "the synthetic panel can stand in for the real sample on this question",
                        "correct": "use the corrected estimate, not the raw synthetic number",
                        "mixed": "some audiences are usable after correction, others are not: see by_group",
                        "walk-away": "the synthetic panel does not cover these people: collect real answers"}[overall]}
