"""Markdown report rendering (with optional redaction of prompt/output text)."""
from __future__ import annotations

import re
from typing import List, Optional

from . import __version__
from .audit import VERDICT_LABELS, VERDICT_ORDER, Audit
from .code_scan import CodeScan
from .heuristics import WEIGHTS
from .selfcheck import SelfcheckResult

_REDACTIONS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh_[REDACTED]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED@email]"),
    (re.compile(r"\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+", re.I), "[REDACTED credential]"),
    (re.compile(r"\bbearer\s+\S+", re.I), "bearer [REDACTED]"),
    (re.compile(r"\b[0-9a-f]{32,}\b", re.I), "[REDACTED hex]"),
]


def redact_text(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ⏎ ")


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def render_markdown(
    audit: Audit,
    top_n: int = 25,
    redact: bool = True,
    scan: Optional[CodeScan] = None,
    selfcheck: Optional[SelfcheckResult] = None,
) -> str:
    scrub = redact_text if redact else (lambda t: t)

    counts = audit.counts()
    spend = audit.spend()
    total_calls = audit.total_calls
    total_spend = audit.total_spend
    savings = audit.savings()
    provenance = audit.cost_provenance()
    n_files = len(audit.files)

    def call_share(v: str) -> str:
        return _pct(counts[v] / total_calls) if total_calls else "0%"

    def spend_share(v: str) -> str:
        return _pct(spend[v] / total_spend) if total_spend else "0%"

    lines: List[str] = []
    add = lines.append

    # ------------------------------------------------------------------ header
    add("# JEV migration audit")
    add("")
    add(
        f"_Generated {audit.generated_at} by should-i-jev v{__version__} — "
        "unofficial community tool, not affiliated with TypeSafe._"
    )
    add("")
    add(
        f"**Inputs:** {n_files} file(s), {total_calls} calls, {len(audit.models)} model(s). "
        f"{audit.skipped_lines} unparseable line(s) skipped."
    )
    add("")

    # ------------------------------------------------------------------ TL;DR
    add("## TL;DR")
    add("")
    add(
        f"- **{counts['likely']} calls ({call_share('likely')}) look JEV-shaped**; "
        f"another {counts['maybe']} ({call_share('maybe')}) are worth a look."
    )
    if counts["insufficient"]:
        add(
            f"- {counts['insufficient']} calls ({call_share('insufficient')}) come from text-less "
            "usage exports and can't be scored on shape alone — wire up a text-bearing log "
            "source (LiteLLM/Langfuse) to audit them."
        )
    if scan is not None and scan.findings:
        add(
            f"- Code scan: **{scan.decision_shaped} of {len(scan.findings)} LLM call sites** "
            f"in `{scan.root}` look decision-shaped."
        )
    add(
        f"- Migratable spend in these logs: **{_money(audit.migratable_spend)} of "
        f"{_money(total_spend)}**."
    )
    if total_spend:
        add(
            f"- Estimated savings: **{_money(savings['conservative'])} "
            f"({_pct(savings['conservative'] / total_spend)})** at a conservative "
            f"÷{audit.divisor} cost divisor; "
            f"{_money(savings['vendor_claim'])} ({_pct(savings['vendor_claim'] / total_spend)}) "
            f"at the vendor-claimed ÷{audit.divisor_optimistic}."
        )
    add(
        "- The vendor also claims ~200× lower latency on decision workloads; "
        "this tool does not measure latency."
    )
    add("")

    # ------------------------------------------------------------------ verdict table
    add("## Verdict breakdown")
    add("")
    add("| Verdict | Calls | Share | Est. cost | Cost share |")
    add("|---|---:|---:|---:|---:|")
    for v in VERDICT_ORDER:
        add(
            f"| {VERDICT_LABELS[v]} | {counts[v]} | {call_share(v)} | "
            f"{_money(spend[v])} | {spend_share(v)} |"
        )
    add(f"| **Total** | **{total_calls}** | **100%** | **{_money(total_spend)}** | **100%** |")
    add("")
    if counts["insufficient"]:
        add(
            "> _insufficient data_ = rows from usage exports with token counts but no prompt/output "
            "text; token shape alone can't identify decisions, so they are excluded from the "
            "migration estimate rather than guessed at."
        )
        add("")
    add("### By model")
    add("")
    add("| Model | Calls | Est. cost | Likely JEV-shaped |")
    add("|---|---:|---:|---:|")
    for row in audit.models_table():
        add(
            f"| `{_cell(row['model'])}` | {row['calls']} | {_money(row['cost'])} | "
            f"{row['likely']} |"
        )
    add("")

    # ------------------------------------------------------------------ signals
    add("## Signals observed")
    add("")
    tally = audit.signal_tally()
    add("| Signal | Weight | Calls matching |")
    add("|---|---:|---:|")
    for name, weight in WEIGHTS.items():
        add(f"| `{name}` | {weight:.2f} | {tally.get(name, 0)} |")
    add("")
    add(
        "Score = Σ(weight × signal). A generative-looking prompt (write / summarize / "
        "draft … with zero decision verbs) additionally scales the score down by 40%."
    )
    dup = audit.duplication_rates()
    if dup:
        add("")
        add("Per-model output duplication rate: " + ", ".join(
            f"`{m}` {r:.0%}" for m, r in dup.items()
        ))
    add("")

    # ------------------------------------------------------------------ candidates
    add(f"## Top migration candidates (top {min(top_n, counts['likely'])} of likely)")
    add("")
    add("| # | Model | In/Out tok | Cost | Score | Signals | Prompt (redacted) | Output |")
    add("|---:|---|---:|---:|---:|---|---|---|")
    for i, (call, detail) in enumerate(audit.top_candidates(top_n), start=1):
        if detail.verdict != "likely":
            continue
        usd, _, _, _ = audit.cost_of(call)
        signals = ", ".join(
            f"{k} ({v:.1f})"
            for k, v in sorted(detail.signals.items(), key=lambda kv: -kv[1])
            if v > 0
        ) or "—"
        in_tok = call.input_tokens if call.input_tokens is not None else "?"
        out_tok = call.output_tokens if call.output_tokens is not None else "?"
        add(
            f"| {i} | `{_cell(call.model)}` | {in_tok}/{out_tok} | {_money(usd)} | "
            f"**{detail.score:.2f}** | {_cell(signals)} | "
            f"{_cell(_clip(scrub(call.prompt_excerpt), 110))} | "
            f"{_cell(_clip(scrub(call.output_excerpt), 40))} |"
        )
    add("")

    # ------------------------------------------------------------------ code sites
    if scan is not None:
        add("## Code call sites")
        add("")
        add(
            f"_Static scan of `{_cell(scan.root)}`: {scan.files_scanned} file(s) scanned, "
            f"{len(scan.findings)} LLM call site(s) found, {scan.decision_shaped} decision-shaped. "
            "Python sites come from AST analysis; JS/TS from pattern matching._"
        )
        add("")
        if scan.findings:
            add("| # | Location | Lang | Model | API | Handling | Score | Verdict | Prompt (redacted) |")
            add("|---|---|---|---|---|---|---:|---|---|")
            for i, f in enumerate(scan.findings, start=1):
                add(
                    f"| {i} | `{_cell(f.path)}:{f.line}` | {f.language} | "
                    f"`{_cell(f.model or '?')}` | `{_cell(f.api)}` | "
                    f"{_cell(', '.join(f.handling) or '—')} | **{f.detail.score:.2f}** | "
                    f"{VERDICT_LABELS.get(f.detail.verdict, f.detail.verdict)} | "
                    f"{_cell(_clip(scrub(f.prompt_excerpt), 70))} |"
                )
        else:
            add("_No LLM call sites found._")
        add("")

    # ------------------------------------------------------------------ self-audit
    if selfcheck is not None and selfcheck.rows:
        add("## Jev self-audit")
        add("")
        if selfcheck.mock:
            add(
                "_Offline stand-in backend (mock): choices mirror the heuristic score — "
                "set `--jev-base-url` (+ `JEV_API_KEY`) to ask a real Jev endpoint._"
            )
        else:
            add("_Answers from a live Jev endpoint._")
        add("")
        add(
            f"_\"Use Jev to find where Jev belongs\": agreement with the heuristics is "
            f"**{selfcheck.agreement:.0%}** over {selfcheck.n} item(s)"
            + (f", {selfcheck.errors} API error(s) skipped" if selfcheck.errors else "")
            + "._"
        )
        add("")
        add("| Origin | Heuristic | Jev says | p | |")
        add("|---|---|---|---:|---|")
        for r in selfcheck.rows:
            mark = "✓" if r.agrees else "✗"
            p = f"{r.p:.2f}" if r.p is not None else "—"
            add(f"| `{_cell(r.origin)}` | {r.heuristic} | {r.choice} | {p} | {mark} |")
        add("")

    # ------------------------------------------------------------------ jev maps
    maps = audit.jev_maps()
    add("## Suggested JEV maps")
    add("")
    if not maps:
        add("_No high-confidence clusters found — nothing to sketch yet._")
    for m in maps:
        add(
            f"### {m['role']} — “{m['template']}” — {m['calls']} call(s), "
            f"score {m['score_range'][0]:.2f}–{m['score_range'][1]:.2f}"
        )
        add("")
        add("```python")
        add("# Sketch only — adapt names, options and question phrasing to your domain.")
        add(f"class {m['role']}({m['kind']}):")
        add(f"    question = {_clip(scrub(m['example']), 90)!r}")
        if m["kind"] == "Score" and m["options"]:
            add(f"    range = ({m['options'][0]:g}, {m['options'][1]:g})   # observed min/max")
        elif m["options"]:
            add(f"    options = {m['options']!r}")
        elif m["note"]:
            add(f"    # {m['note']}")
        add("```")
        add("")

    # ------------------------------------------------------------------ methodology
    add("## Cost & savings methodology")
    add("")
    add(
        f"- Prices as of **{audit.price_as_of}** ({audit.price_source}). "
        "Override with `--price-file` to match your actual contract."
    )
    add(
        f"- Cost provenance: {provenance['logged']} call(s) use costs logged in the input; "
        f"{provenance['estimated']} estimated from token counts × price table "
        "(token counts approximated from text where missing)."
    )
    unknown = audit.unknown_models()
    if unknown:
        add("- Models missing from the price table (priced at the table median — verify!): "
            + "; ".join(f"`{u}`" for u in unknown))
    add(
        f"- JEV cost is modeled as a **divisor scenario**, not an absolute price: "
        f"conservative ÷{audit.divisor}, vendor claim ÷{audit.divisor_optimistic} "
        "(TypeSafe's launch claims JEV is ~400× cheaper and ~200× faster than LLMs "
        "on classification). Savings = migratable_spend × (1 − 1/divisor)."
    )
    add(
        "- Aggregated usage-export rows are expanded via their `request_count`-style column "
        "when present."
    )
    add("- These are heuristics on log shape, not a benchmark — validate on your own "
        "traffic before migrating (see roadmap: calibration harness).")
    add("")

    # ------------------------------------------------------------------ privacy
    add("## Privacy")
    add("")
    add(
        "All parsing, scoring and rendering happens locally in this process; no network "
        "calls are made and nothing is uploaded. Prompt/output excerpts above are redacted "
        "(API keys, tokens, emails, long hex). Re-run with `--no-redact` at your own risk."
    )
    add("")

    # ------------------------------------------------------------------ disclaimer
    add("## Disclaimers")
    add("")
    add(
        "Unofficial community tool; not affiliated with or endorsed by TypeSafe. "
        "Savings figures are directional estimates. MIT licensed."
    )
    add("")
    return "\n".join(lines)
