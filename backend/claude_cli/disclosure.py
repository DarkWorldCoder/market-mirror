"""How this was made: the AI-use disclosure every exported run carries (dashboard section and disclosure.md).

AAPOR's 2026 task-force report on AI in survey research asks for these disclosures when AI stands in for respondents:
that the AI generated the answers, how many real people took part, which model and access method, the dates, whether
the agents carried memory, what a human checked, and the known biases. It also asks that AI-generated data is not
called a poll or a survey. ESOMAR's 20 questions for buyers of AI-based services ask the same about validation,
limits and data lineage. Everything here is read from files the run already saved; nothing is inferred.

Stdlib only.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Tuple

KNOWN_LIMITS = [
    "Simulated answers vary less than real ones (too alike), which makes differences look sharper than they are.",
    "Gaps between segments and between test arms run larger than real ones; the dashboard shrinks them toward the "
    "average and flags close calls.",
    "Simulated people say they would buy more often than real people do; the say-do rules and the real check exist "
    "for that reason.",
    "Fit is best for the US, UK, Canada, Australia, New Zealand and Ireland, and weaker elsewhere.",
    "New product categories, small subgroups and identity-sensitive topics are where simulated panels fail most.",
]


def _e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _models(bundle: Dict[str, Any]) -> List[str]:
    prov = (bundle.get("run_manifest") or {}).get("provenance") or {}
    found = [f'{m.get("model")} ({m.get("provider")})' for m in prov.get("models") or [] if isinstance(m, dict) and m.get("model")]
    if not found:      # older runs: the model each simulated person was written by, then the survey's providers
        idx = [r for r in (bundle.get("config") or {}).get("persona_index") or [] if isinstance(r, dict)]
        seen = {f'{r["model_name"]} ({r["model_provider"]})' if r.get("model_name") else str(r["model_provider"])
                for r in idx if r.get("model_provider") and r.get("model_provider") != "grounded"}
        seen |= {str(r.get("provider")) for r in (bundle.get("survey") or {}).get("responses") or []
                 if isinstance(r, dict) and r.get("provider")} if not seen else set()
        found = sorted(seen)
    return found


def _when(iso: Any) -> str:
    """'2026-10-20T17:04:11' -> '20 Oct 2026, 17:04'; anything else as given."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d %b %Y, %H:%M").lstrip("0")
    except (TypeError, ValueError):
        return str(iso or "")


def facts(bundle: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(label, value) rows, each from a saved file. Missing facts say so instead of guessing."""
    m = bundle.get("run_manifest") or {}
    prov = m.get("provenance") or {}
    cfg = bundle.get("config") or {}
    index = [r for r in cfg.get("persona_index") or [] if isinstance(r, dict) and r.get("kind", "persona") == "persona"]
    grounded = sum(1 for r in index if r.get("model_provider") == "grounded"
                   or str((r.get("provenance") or {}).get("demographics") or "").startswith("real_intake"))
    cal = bundle.get("calibration") or {}
    n_real = cal.get("n_real")
    engine = prov.get("engine") or {}
    emo = m.get("emotions") or {}
    models = _models(bundle)
    rows = [
        ("Who answered", "AI models playing invented people. No real person answered any question in this run."),
        ("Real people compared", f"{n_real} real answers were compared with the simulated ones (see Real-sample check)."
         if n_real else "None yet. Use the real-people check kit to collect some."),
        ("Simulated people", f"{len(index)} invented people" + (f", {grounded} built from real customer records" if grounded else "")
         if index else "Not recorded"),
        ("Model and access", (", ".join(models) + (" (recorded when the run started)" if prov.get("models")
                                                    else " (read from the saved people; access method not recorded)"))
         if models else "Not recorded for this run"),
        ("Dates", " to ".join(x for x in (_when(m.get("started_at")), _when(m.get("finished_at"))) if x) or "Not recorded"),
        ("Memory", f"People kept memories between tests; feelings mode {emo.get('mode')}" if emo.get("mode")
         else "Not recorded"),
        ("Human review", ("Spending was approved explicitly before the paid steps" if prov.get("spend_approved") else
                          "No spend approval was recorded") + (f"; hard cap {prov['max_spend_usd']} USD" if prov.get("max_spend_usd") else "")),
        ("Repeat this run", (f"Engine commit {str(engine['commit'])[:12]}" + (" with local changes" if engine.get("local_changes") else "")
                             if engine.get("commit") else "Engine commit not recorded")
         + (f"; prompt code {prov['services_hash']}" if prov.get("services_hash") else "")
         + (f"; seeds {prov['seeds']}" if prov.get("seeds") else "")),
    ]
    return rows


def markdown(bundle: Dict[str, Any]) -> str:
    lines = ["# How this was made (AI-use disclosure)", "",
             "This is a simulation, not a poll or a survey of real people. Read every number as a direction.", ""]
    lines += [f"- **{k}:** {v}" for k, v in facts(bundle)]
    lines += ["", "## Known limits", ""] + [f"- {x}" for x in KNOWN_LIMITS]
    lines += ["", "Disclosure items follow AAPOR's 2026 report on responsible AI in survey research and ESOMAR's 20 "
                  "questions for buyers of AI-based services.", ""]
    return "\n".join(lines)


def section(bundle: Dict[str, Any], section_head) -> Optional[Tuple[str, str, str]]:
    if not isinstance(bundle, dict) or not (bundle.get("run_manifest") or bundle.get("survey") or bundle.get("config")):
        return None
    rows = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in facts(bundle))
    body = ('<div class="card"><p><strong>This is a simulation, not a poll or a survey of real people.</strong> '
            'Read every number as a direction.</p>'
            f'<dl class="kv">{rows}</dl>'
            '<details style="margin-top:10px"><summary>Known limits of simulated people</summary><ul>'
            + "".join(f"<li>{_e(x)}</li>" for x in KNOWN_LIMITS) + "</ul></details>"
            '<p class="muted small">Items follow AAPOR\'s 2026 report on responsible AI in survey research and ESOMAR\'s '
            "20 questions for buyers of AI-based services. Download disclosure.md to attach it to a deck.</p></div>")
    head = section_head("How this was made", "What answered, what was checked, and what you need to repeat the run.")
    return ("disclosure", "How this was made", head + body)
