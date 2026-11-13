"""Diagnostics and corrections for a synthetic panel against a small real sample (50-300 answers).

Implements the three checks and the doubly-robust correction of arXiv 2609.13148 ("When can you trust your
synthetic users?") in pure Python:

  1. covariate overlap   ESS/N of density-ratio weights from a domain classifier (real vs synthetic on
                         demographics) and that classifier's AUC;
  2. conditional calibration  beta_g = Cov(Y_real, Y_syn | g) / Var(Y_syn | g) per subgroup, from cell means;
  3. (cross-LLM stability is run by the CLI: two panels, min Spearman rho; see `stability`)

and a verdict per subgroup: trust / correct / walk-away. `correct()` returns the AIPW estimate of a rate
(would-convert, CTR, open rate...) with 5-fold cross-fitting and a standard error. `spread_check()` asks whether the
simulated answers, and the gaps between audiences, are as varied as the real ones (simulated panels tend to answer
too alike, which a matching average hides).

Rows are dicts: {"segment", "country", "age", "gender", "y"} with y in [0, 1] (yes = 1, maybe = 0.5, no = 0,
or any rate). Real rows come from the user's own survey / ad export / email stats.
"""

import hashlib
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


# --------------------------------------------------------------------------
# Prediction-powered inference (PPI++): a valid interval from a small real sample plus the simulated panel
# --------------------------------------------------------------------------
#
# Angelopoulos et al., "Prediction-powered inference" (Science 2023) and "PPI++: efficient prediction-powered
# inference" (arXiv 2311.01453); effective sample size as in Broska, Howes & van Loon, "The mixed subjects design"
# (Sociological Methods & Research 2025).
#
# The simulated panel is turned into a predictor f(x) of the answer from demographics (cell means with back-off to
# the segment and to everyone). f is fit on simulated answers only, so it is independent of the real answers.
#   labeled   = the real answers Y_i with f(X_i)                     (n)
#   unlabeled = the simulated people with f(X~_j) and their weight   (N, the target audience's composition)
#   theta     = mean(Y) + lambda * (mean_w f(X~) - mean f(X))
#   var       = Var(Y - lambda f(X)) / n + lambda^2 Var_w(f(X~)) / N_eff
# lambda = Cov(Y, f) / ((1 + n / N_eff) Var(f)), clipped to [0, 1]: when the panel predicts nothing, lambda -> 0
# and the interval is the real-only interval (never worse, up to estimation noise). Validity needs the real
# answers to be a random sample of the audience the simulated panel's weights describe; stratifying by segment
# relaxes that to within each segment.


def _wmean(xs: Sequence[float], ws: Sequence[float]) -> float:
    tot = sum(ws)
    return sum(x * w for x, w in zip(xs, ws)) / tot if tot else 0.0


def _var(xs: Sequence[float]) -> float:
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _cov(xs: Sequence[float], ys: Sequence[float]) -> float:
    xs, ys = list(xs), list(ys)
    if len(xs) < 2:
        return 0.0
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (len(xs) - 1)


def panel_predictor(synthetic: List[Dict[str, Any]], min_cell: int = 3):
    """f(row): the simulated panel's mean answer for that person's cell (segment, country, gender, age band),
    backing off to the segment and then to everyone when a cell has fewer than `min_cell` simulated people."""
    cells: Dict[Any, List[float]] = defaultdict(list)
    segs: Dict[str, List[float]] = defaultdict(list)
    for r in synthetic:
        cells[_cell(r)].append(float(r["y"]))
        segs[str(r.get("segment") or "")].append(float(r["y"]))
    overall = _mean([r["y"] for r in synthetic])

    def f(row: Dict[str, Any]) -> float:
        c = cells.get(_cell(row))
        if c and len(c) >= min_cell:
            return sum(c) / len(c)
        s = segs.get(str(row.get("segment") or ""))
        if s and len(s) >= min_cell:
            return sum(s) / len(s)
        return overall
    return f


def _kish(ws: Sequence[float]) -> float:
    s1, s2 = sum(ws), sum(w * w for w in ws)
    return (s1 * s1 / s2) if s2 else 0.0


def ppi_mean(real: List[Dict[str, Any]], synthetic: List[Dict[str, Any]], lam: Any = "auto", z: float = 1.96,
             predictor=None) -> Dict[str, Any]:
    """PPI++ estimate of the audience mean of y with a z-interval, the real-only interval, lambda and the
    effective sample size (how many real answers alone would give the same precision)."""
    n = len(real)
    if n < 10 or len(synthetic) < 10:
        return {"estimate": None, "reason": "need at least 10 real and 10 simulated answers", "n_real": n,
                "n_synthetic": len(synthetic)}
    f = predictor or panel_predictor(synthetic)
    y = [float(r["y"]) for r in real]
    fl = [f(r) for r in real]
    fu = [f(r) for r in synthetic]
    wu = [max(0.0, float(r.get("weight") or 1.0)) for r in synthetic]
    if not sum(wu):
        wu = [1.0] * len(synthetic)
    n_u = _kish(wu)
    mu_u = _wmean(fu, wu)
    var_fu = sum(w * (x - mu_u) ** 2 for x, w in zip(fu, wu)) / sum(wu) * (len(fu) / max(1, len(fu) - 1))
    var_fl, cov_yf, var_y = _var(fl), _cov(y, fl), _var(y)
    if lam == "auto":
        denom = (1 + n / n_u) * var_fl
        lam_v = cov_yf / denom if denom > 1e-12 else 0.0
    else:
        lam_v = float(lam)
    lam_v = max(0.0, min(1.0, lam_v))
    theta = _mean(y) + lam_v * (mu_u - _mean(fl))
    resid_var = _var([a - lam_v * b for a, b in zip(y, fl)])
    se = math.sqrt(max(0.0, resid_var / n + lam_v ** 2 * var_fu / n_u))
    se_real = math.sqrt(var_y / n) if var_y > 0 else 0.0
    eff = (var_y / (se * se)) if se > 0 and var_y > 0 else float(n)
    corr = cov_yf / math.sqrt(var_y * var_fl) if var_y > 0 and var_fl > 0 else 0.0

    def clip(v: float) -> float:
        return max(0.0, min(1.0, v))
    return {"estimate": round(clip(theta), 4), "se": round(se, 4),
            "ci": [round(clip(theta - z * se), 4), round(clip(theta + z * se), 4)],
            "lambda": round(lam_v, 3), "correlation": round(corr, 3),
            "real_only": {"estimate": round(_mean(y), 4), "se": round(se_real, 4),
                          "ci": [round(clip(_mean(y) - z * se_real), 4), round(clip(_mean(y) + z * se_real), 4)]},
            "panel_mean": round(mu_u, 4), "n_real": n, "n_synthetic": len(synthetic), "n_synthetic_effective": round(n_u, 1),
            "effective_n": round(eff, 1), "worth_extra_real": round(max(0.0, eff - n), 1),
            "_parts": {"var_y": var_y, "cov": cov_yf, "var_fl": var_fl, "var_fu": var_fu, "n_u": n_u, "z": z}}


def ppi_stratified(real: List[Dict[str, Any]], synthetic: List[Dict[str, Any]], key: str = "segment",
                   z: float = 1.96, min_real: int = 10) -> Dict[str, Any]:
    """PPI++ per stratum (the simulated panel's weights give each stratum's share of the audience), combined.
    Strata with fewer than `min_real` real answers are left out and listed; the combined estimate then covers only
    the rest of the audience, and says so."""
    def k(r):
        return str(r.get(key) or "?")
    strata = sorted({k(r) for r in synthetic})
    share: Dict[str, float] = {}
    tot = sum(max(0.0, float(r.get("weight") or 1.0)) for r in synthetic) or 1.0
    for st in strata:
        share[st] = sum(max(0.0, float(r.get("weight") or 1.0)) for r in synthetic if k(r) == st) / tot
    by: Dict[str, Any] = {}
    skipped = []
    for st in strata:
        rs, ss = [r for r in real if k(r) == st], [r for r in synthetic if k(r) == st]
        if len(rs) < min_real or len(ss) < 10:
            skipped.append({"stratum": st, "real": len(rs), "simulated": len(ss), "share": round(share[st], 3)})
            continue
        res = ppi_mean(rs, ss, z=z)
        res.pop("_parts", None)
        by[st] = {**res, "share": round(share[st], 3)}
    covered = sum(v["share"] for v in by.values())
    if not by or covered <= 0:
        return {"estimate": None, "reason": f"no {key} has {min_real}+ real answers", "skipped": skipped}
    est = sum(v["share"] * v["estimate"] for v in by.values()) / covered
    se = math.sqrt(sum((v["share"] / covered) ** 2 * v["se"] ** 2 for v in by.values()))
    eff = sum(v["effective_n"] for v in by.values())
    return {"key": key, "estimate": round(est, 4), "se": round(se, 4),
            "ci": [round(max(0.0, est - z * se), 4), round(min(1.0, est + z * se), 4)],
            "audience_covered": round(covered, 3), "by_stratum": by, "skipped": skipped,
            "effective_n": round(eff, 1), "n_real": sum(v["n_real"] for v in by.values())}


def _ppi_var_at(parts: Dict[str, float], n: int) -> float:
    """Variance of the PPI++ estimate with n real answers, lambda re-tuned for that n (never above real-only)."""
    vy, cov, vf, vfu, nu = parts["var_y"], parts["cov"], parts["var_fl"], parts["var_fu"], parts["n_u"]
    lam = max(0.0, min(1.0, cov / (vf * (1 + n / nu)))) if vf > 1e-12 else 0.0
    with_lam = (vy - 2 * lam * cov + lam * lam * vf) / n + lam * lam * vfu / nu
    return min(with_lam, vy / n)


def plan_humans(res: Dict[str, Any], halfwidth: float = 0.05) -> Dict[str, Any]:
    """How many real answers in total (and how many more) give a +-halfwidth interval with this panel (PPI++,
    lambda re-tuned for each sample size, the variances held at today's estimates) and with real answers alone."""
    parts = res.get("_parts") or {}
    if res.get("estimate") is None or not parts:
        return {"halfwidth": halfwidth, "reason": res.get("reason") or "no PPI estimate"}
    target = (halfwidth / parts["z"]) ** 2
    n_real = res["n_real"]
    alone = math.ceil(parts["var_y"] / target) if parts["var_y"] > 0 else None
    with_panel = None
    if parts["var_y"] > 0:
        lo, hi = 1, max(2, alone or 2)
        if _ppi_var_at(parts, hi) <= target:
            while lo < hi:
                mid = (lo + hi) // 2
                if _ppi_var_at(parts, mid) <= target:
                    hi = mid
                else:
                    lo = mid + 1
            with_panel = lo
    out = {"halfwidth": halfwidth, "real_needed_with_panel": with_panel, "real_needed_alone": alone,
           "more_with_panel": max(0, with_panel - n_real) if with_panel else None,
           "more_alone": max(0, alone - n_real) if alone else None}
    return out


def ppi_summary(real: List[Dict[str, Any]], synthetic: List[Dict[str, Any]], key: str = "segment",
                halfwidth: float = 0.05) -> Dict[str, Any]:
    """The PPI block for calibration.json: overall, by stratum, the sample planner and a plain reading."""
    overall = ppi_mean(real, synthetic)
    plan = plan_humans(overall, halfwidth)
    strat = ppi_stratified(real, synthetic, key)
    overall.pop("_parts", None)
    reading = None
    if overall.get("estimate") is not None:
        lo, hi = overall["ci"]
        reading = (f"With {overall['n_real']} real answers and this panel the audience rate is "
                   f"{100 * overall['estimate']:.1f}% (95% interval {100 * lo:.1f}-{100 * hi:.1f}%). The panel adds the "
                   f"precision of about {overall['worth_extra_real']:.0f} more real answers "
                   f"(lambda {overall['lambda']}, correlation {overall['correlation']}).")
        if plan.get("more_with_panel") is not None:
            reading += (f" For +-{100 * halfwidth:.0f} points: {plan['more_with_panel']} more real answers with the panel"
                        + (f", {plan['more_alone']} without it." if plan.get("more_alone") is not None else "."))
    return {"method": "PPI++ (Angelopoulos et al. 2023)", "overall": overall, "stratified": strat, "plan": plan,
            "reading": reading,
            "assumption": ("The real answers are a random sample of the audience the simulated panel's weights describe "
                           "(within each segment for the stratified estimate). The interval is about that audience's "
                           "stated answer, not about purchases.")}


# --------------------------------------------------------------------------
# Spread: do the simulated people differ from each other as much as real people do?
# --------------------------------------------------------------------------
#
# Simulated panels tend to answer more alike than real people: a lower SD than the matching humans in 154 of 164
# outcomes across 19 studies (Peng et al., "Funhouse mirrors", arXiv 2509.19088), and far fewer distinct answer patterns
# from demographic prompts than from real people (arXiv 2511.21218). A matching average can hide that, so two checks
# run against the real answers:
#   answers    the spread of individual answers (SD ratio, answer shares, Wasserstein-1 on the 0-1 scale). Only when
#              both sides use the same answer scale and it is not yes/no: a yes/no answer's spread is fixed by its rate,
#              which the level check already covers.
#   audiences  how far apart the audiences' averages are. Each average's sampling noise is taken out first (method of
#              moments), so a small real sample does not look more varied than it is.
# Each ratio (simulated / real) gets a 90% stratified bootstrap interval. "Too alike" needs the ratio below 0.8 and
# the whole interval below 1 (a material and a clear gap); "too spread out" the mirror image (above 1.25, interval
# above 1). "Similar" needs the interval to rule out large gaps (inside 0.6-1.67); anything else is "unclear". The
# studies above are mostly US opinion surveys and one survey (ANES) showed near-human spread, so this is measured per
# run, never applied as a fixed correction.

SPREAD_LOW, SPREAD_HIGH = 0.8, 1.25
SIMILAR_BAND = (0.6, 1.67)


def _scale(ys: Sequence[float]) -> str:
    levels = {round(float(y), 4) for y in ys}
    if levels <= {0.0, 1.0}:
        return "yes/no"
    if levels <= {0.0, 0.5, 1.0}:
        return "yes/maybe/no"
    return "scale"


def _wsd(ys: Sequence[float], ws: Sequence[float]) -> float:
    """Weighted SD (population form, weights normalised)."""
    tot = sum(ws)
    if not tot or len(ys) < 2:
        return 0.0
    m = sum(y * w for y, w in zip(ys, ws)) / tot
    return math.sqrt(max(0.0, sum(w * (y - m) ** 2 for y, w in zip(ys, ws)) / tot))


def _shares(ys: Sequence[float], ws: Sequence[float]) -> Dict[str, float]:
    tot = sum(ws) or 1.0
    out: Dict[str, float] = defaultdict(float)
    for y, w in zip(ys, ws):
        out[f"{round(float(y), 4):g}"] += w / tot
    return {k: round(v, 3) for k, v in sorted(out.items(), key=lambda kv: float(kv[0]))}


def _w1(a: Sequence[float], wa: Sequence[float], b: Sequence[float], wb: Sequence[float]) -> float:
    """Wasserstein-1 distance between two weighted samples on the real line (area between the two CDFs)."""
    ta, tb = sum(wa) or 1.0, sum(wb) or 1.0
    ea = sorted(zip(a, wa))
    eb = sorted(zip(b, wb))
    pts = sorted({x for x, _ in ea} | {x for x, _ in eb})
    i = j = 0
    ca = cb = 0.0
    dist = 0.0
    for lo, hi in zip(pts, pts[1:]):
        while i < len(ea) and ea[i][0] <= lo:
            ca += ea[i][1] / ta
            i += 1
        while j < len(eb) and eb[j][0] <= lo:
            cb += eb[j][1] / tb
            j += 1
        dist += abs(ca - cb) * (hi - lo)
    return dist


def _between_sd(groups: Sequence[Sequence[Tuple[float, float]]]) -> Optional[float]:
    """SD of the groups' true averages: the variance of the observed (weighted) averages minus their mean squared
    standard error, floored at 0. groups: [[(y, weight), ...], ...]; None with fewer than two groups."""
    means, noise = [], []
    for rows in groups:
        ys, ws = [y for y, _ in rows], [w for _, w in rows]
        tot = sum(ws)
        if not tot:
            continue
        means.append(sum(y * w for y, w in rows) / tot)
        n_eff = _kish(ws)
        noise.append(_wsd(ys, ws) ** 2 / max(1.0, n_eff - 1))
    if len(means) < 2:
        return None
    return math.sqrt(max(0.0, _var(means) - sum(noise) / len(noise)))


def _interval(ratios: List[float]) -> List[Optional[float]]:
    """90% percentile interval of bootstrap ratios (inf when the real side came out flat in a resample)."""
    if not ratios:
        return [None, None]
    rs = sorted(ratios)
    lo, hi = rs[int(0.05 * (len(rs) - 1))], rs[int(round(0.95 * (len(rs) - 1)))]
    return [round(lo, 3) if math.isfinite(lo) else None, round(hi, 3) if math.isfinite(hi) else None]


def _spread_verdict(ratio: Optional[float], ci: List[Optional[float]]) -> str:
    if ratio is None:
        return "unclear"
    lo, hi = ci
    if ratio < SPREAD_LOW and hi is not None and hi < 1.0:
        return "too alike"
    if ratio > SPREAD_HIGH and lo is not None and lo > 1.0:
        return "too spread out"
    if lo is not None and hi is not None and SIMILAR_BAND[0] <= lo and hi <= SIMILAR_BAND[1]:
        return "similar"
    return "unclear"


def spread_check(synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]], key: str = "segment",
                 min_real: int = 10, min_syn: int = 10, boots: int = 400, seed: int = 11) -> Dict[str, Any]:
    """Are the simulated answers as varied as the real ones? Individual answers and the gaps between audiences,
    each as a simulated/real SD ratio with a 90% bootstrap interval, plus an overall verdict and a plain reading."""
    rng = random.Random(seed)

    def wt(r: Dict[str, Any]) -> float:
        return max(0.0, float(r.get("weight") or 1.0))
    sy, sw = [float(r["y"]) for r in synthetic], [wt(r) for r in synthetic]
    ry = [float(r["y"]) for r in real]
    rw = [1.0] * len(ry)

    # 1. individual answers
    scale_s, scale_r = (_scale(sy) if sy else None), (_scale(ry) if ry else None)
    ans: Dict[str, Any] = {"scale_simulated": scale_s, "scale_real": scale_r, "n_simulated": len(sy), "n_real": len(ry),
                           "levels_simulated": len({round(y, 4) for y in sy}), "levels_real": len({round(y, 4) for y in ry})}
    if len(ry) < min_real or len(sy) < min_real:
        ans.update(verdict="not checked", reason=f"needs {min_real}+ real and simulated answers")
    elif scale_s != scale_r:
        ans.update(verdict="not checked", reason=f"different answer scales (simulated {scale_s}, real {scale_r}); "
                                                 "only the gaps between audiences are compared")
    elif scale_r == "yes/no":
        ans.update(verdict="not checked", reason="yes/no answers: their spread follows the rate, which the level check covers")
    else:
        sd_s, sd_r = _wsd(sy, sw), _wsd(ry, rw)
        if sd_r <= 1e-9:
            ans.update(verdict="not checked", reason="every real answer is the same")
        else:
            ratios = []
            for _ in range(boots):
                si = [rng.randrange(len(sy)) for _ in sy]
                ri = [rng.randrange(len(ry)) for _ in ry]
                b_r = _wsd([ry[i] for i in ri], [1.0] * len(ri))
                ratios.append(_wsd([sy[i] for i in si], [sw[i] for i in si]) / b_r if b_r > 1e-9 else math.inf)
            ratio = sd_s / sd_r
            ci = _interval(ratios)
            ans.update(sd_simulated=round(sd_s, 3), sd_real=round(sd_r, 3), sd_ratio=round(ratio, 3), ratio_interval=ci,
                       wasserstein=round(_w1(sy, sw, ry, rw), 3), verdict=_spread_verdict(ratio, ci))
            if ans["levels_simulated"] <= 11 and ans["levels_real"] <= 11:
                ss, rs = _shares(sy, sw), _shares(ry, rw)
                ans.update(shares_simulated=ss, shares_real=rs,
                           total_variation=round(0.5 * sum(abs(ss.get(k, 0.0) - rs.get(k, 0.0)) for k in set(ss) | set(rs)), 3))

    # 2. gaps between audiences
    def grp(r: Dict[str, Any]) -> str:
        return str((r.get(key) if key != "age_band" else (r.get("age_band") or age_band(r.get("age")))) or "?")
    gs: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    gr: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for r in synthetic:
        gs[grp(r)].append((float(r["y"]), wt(r)))
    for r in real:
        gr[grp(r)].append((float(r["y"]), 1.0))
    used = sorted(g for g in gr if g != "?" and len(gr[g]) >= min_real and len(gs.get(g, [])) >= min_syn)
    left_out = sorted(g for g in set(gs) | set(gr) if g not in used)
    aud: Dict[str, Any] = {"key": key, "groups": [], "left_out": left_out}
    for g in used:
        ms = sum(y * w for y, w in gs[g]) / (sum(w for _, w in gs[g]) or 1.0)
        mr = sum(y for y, _ in gr[g]) / len(gr[g])
        aud["groups"].append({"group": g, "n_simulated": len(gs[g]), "n_real": len(gr[g]), "mean_simulated": round(ms, 3),
                              "mean_real": round(mr, 3)})
    b_s = _between_sd([gs[g] for g in used]) if len(used) >= 2 else None
    b_r = _between_sd([gr[g] for g in used]) if len(used) >= 2 else None
    if b_s is None or b_r is None:
        aud.update(verdict="not checked", reason=f"needs two or more {key}s with {min_real}+ real and {min_syn}+ simulated "
                                                 "answers each")
    else:
        ms_all, mr_all = [x["mean_simulated"] for x in aud["groups"]], [x["mean_real"] for x in aud["groups"]]
        aud.update(between_sd_simulated=round(b_s, 3), between_sd_real=round(b_r, 3),
                   range_simulated=round(max(ms_all) - min(ms_all), 3), range_real=round(max(mr_all) - min(mr_all), 3))
        if b_r <= 1e-9:
            aud.update(verdict="unclear", reason=f"the real {key}s do not differ by more than their sampling noise")
        else:
            ratios = []
            for _ in range(boots):
                rs_s = [[rows[rng.randrange(len(rows))] for _ in rows] for rows in (gs[g] for g in used)]
                rs_r = [[rows[rng.randrange(len(rows))] for _ in rows] for rows in (gr[g] for g in used)]
                bs, br = _between_sd(rs_s) or 0.0, _between_sd(rs_r) or 0.0
                ratios.append(bs / br if br > 1e-9 else math.inf)
            ratio = b_s / b_r
            ci = _interval(ratios)
            aud.update(sd_ratio=round(ratio, 3), ratio_interval=ci, verdict=_spread_verdict(ratio, ci))

    verdicts = [v for v in (ans["verdict"], aud["verdict"]) if v != "not checked"]
    if not verdicts:
        overall = "not checked"
    elif "too alike" in verdicts:
        overall = "too alike"
    elif "too spread out" in verdicts:
        overall = "too spread out"
    elif all(v == "similar" for v in verdicts):
        overall = "similar"
    else:
        overall = "unclear"
    return {"verdict": overall, "flag": overall == "too alike", "answers": ans, "audiences": aud,
            "reading": _spread_reading(overall, ans, aud), "thresholds": {"low": SPREAD_LOW, "high": SPREAD_HIGH},
            "sources": ["arXiv 2509.19088", "arXiv 2511.21218"]}


def _spread_reading(overall: str, ans: Dict[str, Any], aud: Dict[str, Any]) -> str:
    def ci(d: Dict[str, Any]) -> str:
        lo, hi = d.get("ratio_interval") or [None, None]
        return f"90% interval {lo if lo is not None else '?'}-{hi if hi is not None else 'open'}"
    bits = []
    if ans.get("sd_ratio") is not None and ans["verdict"] in ("too alike", "too spread out"):
        more_less = "less" if ans["verdict"] == "too alike" else "more"
        s = (f"Simulated answers vary {more_less} than real ones (SD {ans['sd_simulated']} against {ans['sd_real']}, "
             f"ratio {ans['sd_ratio']}, {ci(ans)}).")
        mid_s, mid_r = (ans.get("shares_simulated") or {}).get("0.5"), (ans.get("shares_real") or {}).get("0.5")
        if mid_s is not None and mid_r is not None and mid_s - mid_r >= 0.15:
            s += f" {round(100 * mid_s)}% of simulated people said maybe, against {round(100 * mid_r)}% of real people."
        bits.append(s)
    if aud.get("sd_ratio") is not None and aud["verdict"] in ("too alike", "too spread out"):
        closer = "closer together" if aud["verdict"] == "too alike" else "further apart"
        span = (f"their averages span {round(100 * aud['range_simulated'])} points against {round(100 * aud['range_real'])}"
                if aud["sd_ratio"] > 0 else
                f"their averages ({round(100 * aud['range_simulated'])} points apart) differ by no more than noise, while the "
                f"real ones span {round(100 * aud['range_real'])}")
        bits.append(f"The simulated {aud['key']}s are {closer} than the real ones: {span} "
                    f"(spread ratio {aud['sd_ratio']}, {ci(aud)}).")
    if overall == "too alike":
        bits.append("Treat differences between simulated people and audiences as understated, and check which audience "
                    "to target against real answers before acting on it.")
    elif overall == "too spread out":
        bits.append("The simulated people disagree more than real ones; treat the extremes as exaggerated.")
    elif overall == "similar":
        bits.append("The simulated answers are about as varied as the real ones.")
    elif overall == "unclear":
        reason = aud.get("reason") if aud["verdict"] == "unclear" and aud.get("reason") else "the interval is still wide"
        bits.append(f"Spread check unclear: {reason}; more real answers would settle it.")
    else:
        bits.append("Spread not checked: " + "; ".join(r for r in (ans.get("reason"), aud.get("reason")) if r) + ".")
    return " ".join(bits)


def diagnose(synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]], key: str = "segment",
             halfwidth: float = 0.05) -> Dict[str, Any]:
    """The full check: overlap, conditional calibration per subgroup, an overall verdict, the AIPW correction, the
    PPI++ interval and the spread check (are the simulated answers as varied as the real ones?)."""
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
            "calibration": cal, "verdict": overall, "corrected": corr, "ppi": ppi_summary(real, synthetic, key, halfwidth),
            "spread": spread_check(synthetic, real, key),
            "reading": {"trust": "the synthetic panel can stand in for the real sample on this question",
                        "correct": "use the corrected estimate, not the raw synthetic number",
                        "mixed": "some audiences are usable after correction, others are not: see by_group",
                        "walk-away": "the synthetic panel does not cover these people: collect real answers"}[overall]}


# --------------------------------------------------------------------------
# Real-sample budget: split a fixed set of real answers between building personas and checking them
# --------------------------------------------------------------------------
#
# Real answers can ground the personas (`intake`) or check and correct the panel (`calibrate`: AIPW, PPI++), not both:
# PPI's guarantee needs answers the panel never saw. With a fixed number of real answers, giving most of them (60-80%)
# to the held-out correction gave the best trade-off between bias and precision, and a 20/80 split the lowest bias
# (Krsteski et al., ACL 2026, arXiv 2510.11408; one dataset, so the exact share will vary). split_plan shows what each
# split costs the check; split_rows splits by person, so one customer's rows never land on both sides; holdout_guard
# drops the persona-building side from a later calibration.

SPLIT_SHARES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
DEFAULT_CONDITIONING = 0.2
MIN_HOLDOUT = 30
SPLIT_SALT = "marketmirror-split-v1"
ID_COLUMNS = ("respondent_id", "response_id", "customer_id", "person_id", "user_id", "contact_id", "id", "email")


def _halfwidths(n: int, var_y: float, rho: float, n_u: float, z: float = 1.96) -> Tuple[float, float]:
    """Half-widths of the real-only and the PPI++ interval with n held-out answers. PPI++ with the best lambda has
    variance var_y / n * (1 - rho^2 / (1 + n / n_u)), taking the panel's prediction variance as the same on both sides."""
    if n <= 0:
        return math.inf, math.inf
    alone = z * math.sqrt(var_y / n)
    shrink = 1 - rho * rho / (1 + n / n_u) if n_u > 0 else 1.0
    return alone, alone * math.sqrt(max(0.0, shrink))


def split_plan(n_people: int, prior: Optional[Dict[str, Any]] = None, halfwidth: float = 0.05,
               shares: Sequence[float] = SPLIT_SHARES, z: float = 1.96) -> Dict[str, Any]:
    """How to split n_people real answers between persona building and the held-out check, with the half-width the
    check reaches at each split. prior: `ppi.overall` from an earlier calibration.json (its correlation, real-only
    standard error, n_real and effective panel size); without one, the worst case for a 0-1 answer and no panel help."""
    n = max(0, int(n_people))
    real_only = (prior or {}).get("real_only") or {}
    if prior and prior.get("correlation") is not None and real_only.get("se") and prior.get("n_real"):
        var_y = float(real_only["se"]) ** 2 * int(prior["n_real"])
        rho = max(-1.0, min(1.0, float(prior["correlation"])))
        n_u = float(prior.get("n_synthetic_effective") or prior.get("n_synthetic") or 0)
        basis = "your last calibration (its panel correlation and answer spread)"
    else:
        var_y, rho, n_u = 0.25, 0.0, 0.0
        basis = "worst case: no calibration yet, so no help from the panel and the widest spread a 0-1 answer can have"
    rows = []
    for c in shares:
        cond = int(round(n * c))
        hold = n - cond
        alone, panel = _halfwidths(hold, var_y, rho, n_u, z)
        rows.append({"conditioning_share": c, "conditioning": cond, "holdout": hold,
                     "halfwidth_alone": round(alone, 3) if math.isfinite(alone) else None,
                     "halfwidth_with_panel": round(panel, 3) if math.isfinite(panel) else None})

    def at(c: float) -> Dict[str, Any]:
        cond = int(round(n * c))
        alone, panel = _halfwidths(n - cond, var_y, rho, n_u, z)
        return {"conditioning_share": c, "conditioning": cond, "holdout": n - cond,
                "halfwidth": round(panel, 3) if math.isfinite(panel) else None}
    if n < MIN_HOLDOUT + 10:
        rec = {**at(0.0), "reason": f"{n} answers are too few to split: keep every one for the check, and ground the "
                                    "personas with other material (reviews, calls, CRM notes)"}
    else:
        fits = [c for c in (DEFAULT_CONDITIONING, 0.1, 0.0)
                if n - int(round(n * c)) >= MIN_HOLDOUT and (at(c)["halfwidth"] or math.inf) <= halfwidth]
        if fits and fits[0] == DEFAULT_CONDITIONING:
            rec = {**at(DEFAULT_CONDITIONING), "reason": f"20% builds personas and 80% checks them, the split with the "
                                                         f"lowest bias; the check still reaches +-{halfwidth:g}"}
        elif fits:
            c = fits[0]
            rec = {**at(c), "reason": (f"a 20% share would widen the check past +-{halfwidth:g}; "
                                       + ("10% keeps it inside" if c else "every answer is needed to reach it"))}
        else:
            rec = {**at(DEFAULT_CONDITIONING), "reason": f"no split reaches +-{halfwidth:g}; 20/80 keeps the bias lowest"}
    need = None
    if var_y > 0:
        lo, hi = 1, 1
        while _halfwidths(hi, var_y, rho, n_u, z)[1] > halfwidth and hi < 10 ** 7:
            hi *= 2
        while lo < hi:
            mid = (lo + hi) // 2
            if _halfwidths(mid, var_y, rho, n_u, z)[1] <= halfwidth:
                hi = mid
            else:
                lo = mid + 1
        need = lo
    c = rec["conditioning_share"]
    total_needed = math.ceil(need / (1 - c)) if need and c < 1 else None
    rec["holdout_needed"] = need
    rec["more_real_needed"] = max(0, total_needed - n) if total_needed else None
    return {"people": n, "halfwidth_target": halfwidth, "basis": basis,
            "assumptions": {"answer_sd": round(math.sqrt(var_y), 3), "panel_correlation": round(rho, 3),
                            "panel_effective_n": round(n_u, 1)},
            "table": rows, "recommended": rec,
            "rule": "Answers that build personas never go into the check; the check needs answers the panel never saw.",
            "source": "Krsteski et al., ACL 2026 (arXiv 2510.11408)"}


def hash_id(value: Any, salt: str = SPLIT_SALT) -> str:
    """A salted hash of a person id, so the split manifest never stores emails or customer ids themselves."""
    return hashlib.sha256(f"{salt}:{str(value).strip().lower()}".encode("utf-8")).hexdigest()[:16]


def id_column(rows: Sequence[Dict[str, Any]], id_field: str = "") -> str:
    if id_field:
        return id_field
    cols = {str(k).strip().lower(): k for r in rows[:50] for k in r}
    return next((cols[c] for c in ID_COLUMNS if c in cols), "")


def split_rows(rows: List[Dict[str, Any]], conditioning_share: float, id_field: str = "", segment_field: str = "",
               seed: int = 7, salt: str = SPLIT_SALT) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Split real rows by person: every row with the same id lands on the same side. Within each segment the people
    are shuffled with a fixed seed and round(share x people) go to persona building, so both sides cover every
    segment. Rows without an id column count as one person each. Returns (conditioning, holdout, manifest)."""
    share = max(0.0, min(0.9, float(conditioning_share)))
    col = id_column(rows, id_field)
    person_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seg_of: Dict[str, str] = {}
    for i, r in enumerate(rows):
        raw = str(r.get(col) or "").strip() if col else ""
        pid = hash_id(raw, salt) if raw else f"row{i + 1}"
        person_rows[pid].append(r)
        seg_of.setdefault(pid, str(r.get(segment_field) or "").strip() if segment_field else "")
    by_seg: Dict[str, List[str]] = defaultdict(list)
    for pid, seg in seg_of.items():
        by_seg[seg].append(pid)
    cond_ids: List[str] = []
    counts: Dict[str, Dict[str, int]] = {}
    for seg in sorted(by_seg):
        ids = sorted(by_seg[seg])
        random.Random(f"{seed}:{seg}").shuffle(ids)
        k = int(round(share * len(ids)))
        if k >= len(ids) and len(ids) > 1:
            k = len(ids) - 1                     # every segment keeps someone in the check
        cond_ids += ids[:k]
        counts[seg or "(all)"] = {"conditioning": k, "holdout": len(ids) - k}
    cond = set(cond_ids)
    conditioning = [r for pid in person_rows if pid in cond for r in person_rows[pid]]
    holdout = [r for pid in person_rows if pid not in cond for r in person_rows[pid]]
    manifest = {"version": 1, "salt": salt, "seed": seed, "id_field": col, "segment_field": segment_field,
                "conditioning_share": share, "people": len(person_rows), "rows": len(rows),
                "counts": {"conditioning": len(cond), "holdout": len(person_rows) - len(cond),
                           "conditioning_rows": len(conditioning), "holdout_rows": len(holdout)},
                "by_segment": counts,
                "conditioning_ids": sorted(cond) if col else [],
                "note": ("ids are salted hashes, not the raw ids" if col else
                         "no id column: each row is one person, so a later calibration can only be checked by file")}
    return conditioning, holdout, manifest


def holdout_guard(rows: List[Dict[str, Any]], manifest: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Drop rows whose person built the personas (their hashed id is on the manifest's conditioning side), so the
    check only uses answers the panel never saw."""
    if not manifest:
        return rows, {"status": "no split"}
    col = manifest.get("id_field") or ""
    if not col:
        return rows, {"status": "no ids", "reason": manifest.get("note")}
    cond = set(manifest.get("conditioning_ids") or [])
    salt = manifest.get("salt") or SPLIT_SALT
    kept, removed, no_id = [], 0, 0
    for r in rows:
        raw = str(r.get(col) or "").strip()
        if not raw:
            no_id += 1
            kept.append(r)
        elif hash_id(raw, salt) in cond:
            removed += 1
        else:
            kept.append(r)
    return kept, {"status": "removed" if removed else "clean", "removed": removed, "kept": len(kept), "no_id": no_id,
                  "id_field": col}
